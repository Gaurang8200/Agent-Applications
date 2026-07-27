"""Discover orchestration: fetch -> filter -> persist.

Persists kept postings as JobPosting rows (deduped on source + external_id) and
records a Match per posting with the skills that matched. The naive score here
is just the count of matched skills — the dedicated Match stage will replace it
with vector + LLM scoring. status stays "new" for user triage.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.discover.filters import JobFilterConfig, evaluate
from app.agents.discover.sources import (
    ArbeitnowSource,
    ArbeitsagenturSource,
    GreenhouseSource,
    JobSource,
    LeverSource,
    NormalizedPosting,
    SmartRecruitersSource,
)
from app.core.config import get_settings
from app.models import JobPosting, Match, Profile

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class DiscoverySummary:
    scanned: int
    kept: int
    new_postings: int
    new_matches: int
    # Postings fetched per source, and any source that failed outright.
    per_source: dict[str, int] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)


def default_sources() -> list[JobSource]:
    """The configured source set.

    The federal agency carries volume; the ATS boards carry the large
    employers that never post to a job board. Company lists are configuration,
    so adding an employer needs no code change.
    """
    sources: list[JobSource] = [ArbeitsagenturSource(), ArbeitnowSource()]
    if settings.greenhouse_board_list:
        sources.append(GreenhouseSource(settings.greenhouse_board_list))
    if settings.lever_handle_list:
        sources.append(LeverSource(settings.lever_handle_list))
    if settings.smartrecruiters_company_list:
        sources.append(SmartRecruitersSource(settings.smartrecruiters_company_list))
    return sources


def _upsert_posting(db: Session, posting: NormalizedPosting) -> tuple[JobPosting, bool]:
    existing = db.scalar(
        select(JobPosting).where(
            JobPosting.source == posting.source,
            JobPosting.external_id == posting.external_id,
        )
    )
    if existing is not None:
        existing.title = posting.title
        existing.company = posting.company
        existing.location = posting.location
        existing.is_remote = posting.is_remote
        existing.description = posting.description
        existing.url = posting.url
        existing.posted_at = posting.posted_at
        existing.raw_payload = posting.raw
        return existing, False

    row = JobPosting(
        source=posting.source,
        external_id=posting.external_id,
        url=posting.url,
        title=posting.title,
        company=posting.company,
        location=posting.location,
        is_remote=posting.is_remote,
        description=posting.description,
        posted_at=posting.posted_at,
        raw_payload=posting.raw,
    )
    db.add(row)
    db.flush()  # assign id for the Match FK
    return row, True


def _upsert_match(
    db: Session, profile: Profile, posting: JobPosting, matched: list[str]
) -> bool:
    existing = db.scalar(
        select(Match).where(
            Match.profile_id == profile.id, Match.job_posting_id == posting.id
        )
    )
    score = float(len(matched))
    if existing is not None:
        existing.matched_skills = matched
        # Only refresh the placeholder score; never clobber a real one from the
        # Match stage (which sets llm_score).
        if existing.llm_score is None:
            existing.final_score = score
        return False

    db.add(
        Match(
            profile_id=profile.id,
            job_posting_id=posting.id,
            matched_skills=matched,
            final_score=score,
            status="new",
        )
    )
    return True


def discover_jobs(
    db: Session,
    profile: Profile,
    *,
    config: JobFilterConfig | None = None,
    sources: list[JobSource] | None = None,
    max_pages: int = 3,
) -> DiscoverySummary:
    """Fetch from every configured source, filter, and record matches.

    A source that fails is recorded and skipped rather than aborting the run —
    one retired board token or a rate-limited API should not cost the user the
    other sources' results.
    """
    config = config or JobFilterConfig()
    sources = sources if sources is not None else default_sources()
    skills = [s.name for s in profile.skills]

    postings: list[NormalizedPosting] = []
    per_source: dict[str, int] = {}
    failed: list[str] = []

    for source in sources:
        try:
            fetched = source.fetch(
                within_days=config.posted_within_days, max_pages=max_pages
            )
        except Exception as exc:  # noqa: BLE001 - isolate per-source failures
            logger.warning("Source %s failed: %s", source.name, exc)
            failed.append(source.name)
            continue
        per_source[source.name] = len(fetched)
        postings.extend(fetched)

    kept = new_postings = new_matches = 0
    for posting in postings:
        decision = evaluate(
            title=posting.title,
            company=posting.company,
            text=posting.search_text,
            posted_at=posting.posted_at,
            skills=skills,
            config=config,
            location=posting.location,
            country=posting.country,
        )
        if not decision.keep:
            continue
        kept += 1
        row, created_posting = _upsert_posting(db, posting)
        if created_posting:
            new_postings += 1
        if _upsert_match(db, profile, row, decision.matched_skills):
            new_matches += 1

    db.commit()
    return DiscoverySummary(
        scanned=len(postings),
        kept=kept,
        new_postings=new_postings,
        new_matches=new_matches,
        per_source=per_source,
        failed_sources=failed,
    )
