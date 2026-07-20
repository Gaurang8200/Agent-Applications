import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkExperienceIn(BaseModel):
    company: str
    title: str
    location: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    highlights: list[str] = Field(default_factory=list)
    display_order: int = 0


class WorkExperienceOut(WorkExperienceIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class EducationIn(BaseModel):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    grade: str | None = None
    display_order: int = 0


class EducationOut(EducationIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class SkillIn(BaseModel):
    name: str
    category: str | None = None
    years: int | None = None


class SkillOut(SkillIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class ProfileIn(BaseModel):
    headline: str | None = None
    summary: str | None = None
    location: str | None = None
    phone: str | None = None
    links: dict[str, str] = Field(default_factory=dict)
    years_experience: int | None = None
    desired_roles: list[str] = Field(default_factory=list)
    desired_locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    min_salary: int | None = None
    requires_sponsorship: bool | None = None


class ProfileOut(ProfileIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    work_experience: list[WorkExperienceOut] = Field(default_factory=list)
    education: list[EducationOut] = Field(default_factory=list)
    skills: list[SkillOut] = Field(default_factory=list)


class ParsedResume(BaseModel):
    """What the extractor returns. The user reviews and edits this before it is
    promoted into the profile — nothing here is trusted as final."""

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    links: dict[str, str] = Field(default_factory=dict)
    work_experience: list[WorkExperienceIn] = Field(default_factory=list)
    education: list[EducationIn] = Field(default_factory=list)
    skills: list[SkillIn] = Field(default_factory=list)
    # "llm" when Claude parsed it, "heuristic" for the no-API-key fallback.
    extraction_method: str = "heuristic"
    confidence: float | None = None


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    parse_status: str
    parse_error: str | None = None
    is_primary: bool
    created_at: datetime


class ResumeUploadResponse(BaseModel):
    resume: ResumeOut
    parsed: ParsedResume | None = None
