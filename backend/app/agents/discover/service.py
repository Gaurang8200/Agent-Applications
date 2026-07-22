"""Discover orchestration: fetch -> filter -> persist.

Persists kept postings as JobPosting rows (deduped on source + external_id) and
records a Match per posting with the skills that matched. The naive score here
is just the count of matched skills — the dedicated Match stage will replace it
with vector + LLM scoring. status stays "new" for user triage.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.discover.filters import JobFilterConfig, evaluate
from app.agents.discover.sources import ArbeitnowSource, NormalizedPosting
from app.models import JobPosting, Match, Profile


@dataclass
class DiscoverySummary:
    scanned: int
    kept: int
    new_postings: int
    new_matches: int


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
    source: ArbeitnowSource | None = None,
    max_pages: int = 3,
) -> DiscoverySummary:
    config = config or JobFilterConfig()
    source = source or ArbeitnowSource()
    skills = [s.name for s in profile.skills]

    postings = source.fetch(max_pages=max_pages)
    kept = new_postings = new_matches = 0

    for posting in postings:
        decision = evaluate(
            title=posting.title,
            company=posting.company,
            text=posting.search_text,
            posted_at=posting.posted_at,
            skills=skills,
            config=config,
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
    )
