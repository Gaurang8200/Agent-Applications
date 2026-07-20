import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

# The agent may advance an application as far as `ready_for_review`. Only an
# explicit user action moves it to `submitted` — never the agent.
APPLICATION_STATUSES = (
    "draft",
    "tailoring",
    "prefilling",
    "ready_for_review",
    "submitted",
    "acknowledged",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
)

AGENT_TERMINAL_STATUS = "ready_for_review"


class Application(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "applications"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)

    tailored_resume: Mapped[dict | None] = mapped_column(JSONB)
    tailored_resume_s3_key: Mapped[str | None] = mapped_column(String(1000))
    cover_letter: Mapped[str | None] = mapped_column(Text)

    # Field values the prefill agent staged, awaiting user review.
    prefill_payload: Mapped[dict | None] = mapped_column(JSONB)
    prefill_screenshot_s3_key: Mapped[str | None] = mapped_column(String(1000))

    # Set only by a user action, never by an agent. Audit trail for the gate.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)

    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.created_at",
    )


class ApplicationEvent(Base, UUIDMixin, TimestampMixin):
    """Append-only history: who or what changed an application, and when."""

    __tablename__ = "application_events"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    # "agent" | "user" | "system"
    actor: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    message: Mapped[str | None] = mapped_column(Text)

    application: Mapped["Application"] = relationship(back_populates="events")
