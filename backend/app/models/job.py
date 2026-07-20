import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.profile import EMBEDDING_DIM


class JobPosting(Base, UUIDMixin, TimestampMixin):
    """A posting pulled from a job-board API.

    Sourced only from documented public APIs (Adzuna, USAJobs, Greenhouse and
    Lever public boards) — we do not scrape sites that forbid it.
    """

    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),
    )

    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(255))
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)

    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(10))
    employment_type: Mapped[str | None] = mapped_column(String(50))

    # Which ATS renders the apply form; drives which prefill adapter runs.
    ats_vendor: Mapped[str | None] = mapped_column(String(50))
    apply_url: Mapped[str | None] = mapped_column(String(2000))

    requirements: Mapped[list] = mapped_column(JSONB, default=list)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    matches: Mapped[list["Match"]] = relationship(
        back_populates="job_posting", cascade="all, delete-orphan"
    )


class Match(Base, UUIDMixin, TimestampMixin):
    """A scored profile↔posting pair, with the reasoning kept for the UI."""

    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("profile_id", "job_posting_id", name="uq_match_profile_job"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    job_posting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_postings.id", ondelete="CASCADE"), index=True
    )

    # Cosine similarity of the two embeddings, before any LLM judgement.
    vector_score: Mapped[float | None] = mapped_column(Float)
    # Claude's 0-100 judgement of fit.
    llm_score: Mapped[float | None] = mapped_column(Float)
    final_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)

    reasoning: Mapped[str | None] = mapped_column(Text)
    matched_skills: Mapped[list] = mapped_column(JSONB, default=list)
    missing_skills: Mapped[list] = mapped_column(JSONB, default=list)

    # User triage: new -> saved | dismissed
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)

    job_posting: Mapped["JobPosting"] = relationship(back_populates="matches")
