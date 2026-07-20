import uuid
from datetime import date
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User

# voyage-3 / text-embedding-3-small dimensionality. Change here and in the
# migration together if you swap embedding models.
EMBEDDING_DIM = 1024


class Profile(Base, UUIDMixin, TimestampMixin):
    """The canonical, user-verified representation of a candidate.

    Tailoring is grounded strictly in this table — the agent may rephrase what
    is here, never invent beyond it.
    """

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    headline: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    links: Mapped[dict] = mapped_column(JSONB, default=dict)  # linkedin, github, portfolio

    years_experience: Mapped[int | None] = mapped_column(Integer)
    desired_roles: Mapped[list] = mapped_column(JSONB, default=list)
    desired_locations: Mapped[list] = mapped_column(JSONB, default=list)
    remote_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    min_salary: Mapped[int | None] = mapped_column(Integer)
    requires_sponsorship: Mapped[bool | None] = mapped_column(Boolean)

    # Semantic fingerprint of the whole profile, used for job matching.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    user: Mapped["User"] = relationship(back_populates="profile")
    resumes: Mapped[list["Resume"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    work_experience: Mapped[list["WorkExperience"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    education: Mapped[list["Education"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    skills: Mapped[list["Skill"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class Resume(Base, UUIDMixin, TimestampMixin):
    """An uploaded source document plus the raw text we extracted from it."""

    __tablename__ = "resumes"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1000), nullable=False)

    raw_text: Mapped[str | None] = mapped_column(Text)
    # Whatever the extractor returned, kept verbatim so we can re-run parsing
    # without asking the user to re-upload.
    parsed_payload: Mapped[dict | None] = mapped_column(JSONB)
    parse_status: Mapped[str] = mapped_column(String(30), default="pending")
    parse_error: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    profile: Mapped["Profile"] = relationship(back_populates="resumes")


class WorkExperience(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "work_experience"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    # Kept as discrete bullets so tailoring can select and reorder them.
    highlights: Mapped[list] = mapped_column(JSONB, default=list)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    profile: Mapped["Profile"] = relationship(back_populates="work_experience")


class Education(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "education"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    degree: Mapped[str | None] = mapped_column(String(255))
    field_of_study: Mapped[str | None] = mapped_column(String(255))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    grade: Mapped[str | None] = mapped_column(String(50))
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    profile: Mapped["Profile"] = relationship(back_populates="education")


class Skill(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "skills"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(80))
    years: Mapped[int | None] = mapped_column(Integer)

    profile: Mapped["Profile"] = relationship(back_populates="skills")
