"""The autonomous loop: discover, score, and prepare while the user is away.

One cycle walks the pipeline for every profile: pull new postings, score the
unscored ones, then prepare documents for the best matches that do not have an
application yet. Every prepared application stops at `ready_for_review`.

The loop never submits. Submitting means contacting a real employer under the
user's name, so it stays an explicit human action — the same rule the tracker
enforces structurally.

Caps bound each cycle: scoring and preparation both have per-run limits, and
preparation only runs for matches above a score threshold. Without those, a
single overnight cycle could spend an unbounded amount of API budget.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.discover.service import discover_jobs
from app.agents.match_service import score_pending
from app.core.config import get_settings
from app.models import Application, Match, Profile
from app.services import tracker

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class CycleReport:
    started_at: datetime
    finished_at: datetime | None = None
    profiles: int = 0
    discovered: int = 0
    scored: int = 0
    prepared: int = 0
    # Company names whose documents were prepared this cycle.
    prepared_for: list[str] = field(default_factory=list)
    # Human-readable problems: a source that failed, a posting that could not
    # be tailored. Surfaced so an overnight run is auditable.
    problems: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


# In-memory history of recent cycles. The loop lives in the API process, so the
# history is lost on restart; that is acceptable for an audit surface whose
# durable record is the application_events table.
_history: list[CycleReport] = []
_HISTORY_LIMIT = 20


def history() -> list[CycleReport]:
    return list(reversed(_history))


def _record(report: CycleReport) -> None:
    _history.append(report)
    del _history[:-_HISTORY_LIMIT]


def _candidates_for_preparation(
    db: Session, profile: Profile, *, min_score: float, limit: int
) -> list[Match]:
    """Best-scored matches that are not already tracked as an application."""
    tracked = set(
        db.scalars(
            select(Application.job_posting_id).where(
                Application.profile_id == profile.id
            )
        )
    )
    matches = db.scalars(
        select(Match)
        .where(
            Match.profile_id == profile.id,
            Match.llm_score.isnot(None),
            Match.final_score >= min_score,
            Match.status != "dismissed",
        )
        .order_by(Match.final_score.desc())
        # Over-fetch, then filter out the tracked ones in Python — the tracked
        # set is small and this keeps the query simple.
        .limit(limit * 4)
    )
    picked: list[Match] = []
    for match in matches:
        if match.job_posting_id in tracked:
            continue
        picked.append(match)
        if len(picked) >= limit:
            break
    return picked


def _prepare_one(db: Session, profile: Profile, match: Match, report: CycleReport) -> bool:
    """Tailor and render documents for one match, then park it for review."""
    from app.services.docx_prepare import DocxPrepareError, prepare_application

    cv_path = Path(settings.cv_template_path).expanduser()
    letter_path = Path(settings.anschreiben_template_path).expanduser()
    if not cv_path.is_absolute():
        cv_path = (Path.cwd() / cv_path).resolve()
    if not letter_path.is_absolute():
        letter_path = (Path.cwd() / letter_path).resolve()
    if not cv_path.exists() or not letter_path.exists():
        report.problems.append(
            "CV or Anschreiben template missing; cannot prepare documents"
        )
        return False

    posting = match.job_posting
    application = tracker.create_application(db, profile, posting, actor="agent")
    try:
        tracker.transition(
            db, application, to_status="tailoring", actor="agent",
            message="Autopilot tailoring",
        )
        files, result, line_problems = prepare_application(
            cv_template=cv_path,
            anschreiben_template=letter_path,
            job_description=posting.description or posting.title,
            job_title=posting.title,
            company=posting.company,
        )
    except (DocxPrepareError, RuntimeError, ValueError) as exc:
        report.problems.append(f"{posting.company}: {exc}")
        # Leave it in tailoring so the next cycle can retry rather than
        # silently presenting an empty application as ready.
        return False

    tracker.attach_documents(
        db,
        application,
        cover_letter=result.anschreiben.body,
        cv_local_path=files.cv_pdf,
        cover_letter_local_path=files.anschreiben_pdf,
    )
    tracker.transition(
        db, application, to_status="ready_for_review", actor="agent",
        message="Documents prepared by autopilot; awaiting your review",
        payload={"line_problems": line_problems, "compliant": result.compliant},
    )
    if line_problems:
        report.problems.append(
            f"{posting.company}: {len(line_problems)} bullet length issues remain"
        )
    report.prepared_for.append(posting.company)
    return True


def run_cycle(
    db: Session,
    *,
    score_limit: int | None = None,
    prepare_limit: int | None = None,
    min_score: float | None = None,
) -> CycleReport:
    """One full pass of the pipeline for every profile, stopping at review."""
    score_limit = score_limit if score_limit is not None else settings.autopilot_score_limit
    prepare_limit = (
        prepare_limit if prepare_limit is not None else settings.autopilot_prepare_limit
    )
    min_score = min_score if min_score is not None else settings.autopilot_min_score

    report = CycleReport(started_at=datetime.now(UTC))
    profiles = list(db.scalars(select(Profile)))
    report.profiles = len(profiles)

    for profile in profiles:
        if not profile.skills:
            continue  # nothing to match against yet

        try:
            summary = discover_jobs(db, profile)
            report.discovered += summary.new_matches
            for name in summary.failed_sources:
                report.problems.append(f"source {name} failed")
        except Exception as exc:  # noqa: BLE001 - one profile must not stop the cycle
            report.problems.append(f"discovery failed: {exc}")

        if settings.llm_enabled:
            try:
                scoring = score_pending(db, profile, limit=score_limit)
                report.scored += scoring.scored
                if scoring.failed:
                    report.problems.append(f"{scoring.failed} postings failed scoring")
            except Exception as exc:  # noqa: BLE001
                report.problems.append(f"scoring failed: {exc}")

            for match in _candidates_for_preparation(
                db, profile, min_score=min_score, limit=prepare_limit
            ):
                if _prepare_one(db, profile, match, report):
                    report.prepared += 1
        else:
            report.problems.append(
                "ANTHROPIC_API_KEY not set; scoring and tailoring skipped"
            )

    report.finished_at = datetime.now(UTC)
    _record(report)
    logger.info(
        "Autopilot cycle: discovered=%s scored=%s prepared=%s problems=%s",
        report.discovered, report.scored, report.prepared, len(report.problems),
    )
    return report
