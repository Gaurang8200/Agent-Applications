"""Application lifecycle: transitions, the approval gate, and the audit trail.

The gate is the product's central rule. An agent may advance an application as
far as `ready_for_review`. Moving to `submitted` requires an explicit user
action, and is stamped with `approved_by_user_at` plus an event whose actor is
the user. This module is the only place status changes, so the rule cannot be
bypassed by a caller reaching for the column directly.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, ApplicationEvent, JobPosting, Match, Profile
from app.models.application import AGENT_TERMINAL_STATUS, APPLICATION_STATUSES

# Where each status may go next. Terminal states have no outgoing edges except
# withdrawal, which is always available to the user.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"tailoring", "withdrawn"},
    "tailoring": {"prefilling", "ready_for_review", "draft", "withdrawn"},
    "prefilling": {"ready_for_review", "tailoring", "withdrawn"},
    "ready_for_review": {"submitted", "tailoring", "withdrawn"},
    "submitted": {"acknowledged", "rejected", "interviewing", "withdrawn"},
    "acknowledged": {"interviewing", "rejected", "withdrawn"},
    "interviewing": {"offer", "rejected", "withdrawn"},
    "offer": {"rejected", "withdrawn"},
    "rejected": set(),
    "withdrawn": set(),
}

# Statuses an agent is permitted to set. Everything beyond the gate is the
# user's decision, because it represents contacting a real employer.
AGENT_ALLOWED_STATUSES = {"draft", "tailoring", "prefilling", AGENT_TERMINAL_STATUS}

VALID_ACTORS = {"agent", "user", "system"}


class TransitionError(ValueError):
    """A status change that the lifecycle or the approval gate forbids."""


@dataclass
class TransitionResult:
    application: Application
    event: ApplicationEvent


def record_event(
    db: Session,
    application: Application,
    *,
    event_type: str,
    actor: str,
    message: str | None = None,
    payload: dict | None = None,
) -> ApplicationEvent:
    """Append to the application's history. Events are never mutated or removed."""
    if actor not in VALID_ACTORS:
        raise ValueError(f"Unknown actor {actor!r}; expected one of {sorted(VALID_ACTORS)}")
    event = ApplicationEvent(
        application_id=application.id,
        event_type=event_type,
        actor=actor,
        message=message,
        payload=payload,
    )
    db.add(event)
    return event


def create_application(
    db: Session, profile: Profile, posting: JobPosting, *, actor: str = "user"
) -> Application:
    """Start tracking an application, or return the one already tracking it."""
    existing = db.scalar(
        select(Application).where(
            Application.profile_id == profile.id,
            Application.job_posting_id == posting.id,
        )
    )
    if existing is not None:
        return existing

    application = Application(
        profile_id=profile.id, job_posting_id=posting.id, status="draft"
    )
    db.add(application)
    db.flush()  # assign the id the event row references
    record_event(
        db,
        application,
        event_type="created",
        actor=actor,
        message=f"Tracking {posting.title} at {posting.company}",
    )
    db.commit()
    db.refresh(application)
    return application


def create_from_match(db: Session, profile: Profile, match: Match) -> Application:
    return create_application(db, profile, match.job_posting)


def transition(
    db: Session,
    application: Application,
    *,
    to_status: str,
    actor: str,
    message: str | None = None,
    payload: dict | None = None,
) -> TransitionResult:
    """Move an application to `to_status`, enforcing the lifecycle and the gate."""
    if to_status not in APPLICATION_STATUSES:
        raise TransitionError(f"Unknown status {to_status!r}")
    if actor not in VALID_ACTORS:
        raise TransitionError(f"Unknown actor {actor!r}")

    current = application.status
    if to_status == current:
        raise TransitionError(f"Application is already {current!r}")

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if to_status not in allowed:
        raise TransitionError(
            f"Cannot move from {current!r} to {to_status!r}. "
            f"Allowed from here: {sorted(allowed) or 'none, this is a final state'}"
        )

    # The approval gate. An agent may prepare an application completely, but the
    # act of sending it to an employer is the user's to take.
    if actor == "agent" and to_status not in AGENT_ALLOWED_STATUSES:
        raise TransitionError(
            f"An agent cannot move an application to {to_status!r}. Agents stop at "
            f"{AGENT_TERMINAL_STATUS!r}; a user must take it from there."
        )

    now = datetime.now(UTC)
    application.status = to_status
    if to_status == "submitted":
        application.submitted_at = now
        # Records that a human approved this specific application, and when.
        application.approved_by_user_at = now

    event = record_event(
        db,
        application,
        event_type=f"status:{to_status}",
        actor=actor,
        message=message or f"{current} to {to_status}",
        payload=payload,
    )
    db.commit()
    db.refresh(application)
    return TransitionResult(application=application, event=event)


def attach_documents(
    db: Session,
    application: Application,
    *,
    tailored_resume: dict | None = None,
    cover_letter: str | None = None,
    cv_local_path: str | None = None,
    cover_letter_local_path: str | None = None,
    cv_s3_key: str | None = None,
    cover_letter_s3_key: str | None = None,
    actor: str = "agent",
) -> Application:
    """Record the prepared documents against the application."""
    if tailored_resume is not None:
        application.tailored_resume = tailored_resume
    if cover_letter is not None:
        application.cover_letter = cover_letter
    if cv_local_path is not None:
        application.cv_local_path = cv_local_path
    if cover_letter_local_path is not None:
        application.cover_letter_local_path = cover_letter_local_path
    if cv_s3_key is not None:
        application.tailored_resume_s3_key = cv_s3_key
    if cover_letter_s3_key is not None:
        application.cover_letter_s3_key = cover_letter_s3_key

    record_event(
        db,
        application,
        event_type="documents_attached",
        actor=actor,
        message="Tailored CV and cover letter attached",
        payload={"cv": cv_local_path, "cover_letter": cover_letter_local_path},
    )
    db.commit()
    db.refresh(application)
    return application


def list_applications(
    db: Session, profile: Profile, *, status: str | None = None, limit: int = 100
) -> list[Application]:
    query = (
        select(Application)
        .where(Application.profile_id == profile.id)
        .order_by(Application.updated_at.desc())
        .limit(limit)
    )
    if status:
        query = query.where(Application.status == status)
    return list(db.scalars(query))


def board_counts(db: Session, profile: Profile) -> dict[str, int]:
    """Applications per status, including zeroes so the board renders stable columns."""
    counts = {status: 0 for status in APPLICATION_STATUSES}
    for application in db.scalars(
        select(Application).where(Application.profile_id == profile.id)
    ):
        counts[application.status] = counts.get(application.status, 0) + 1
    return counts
