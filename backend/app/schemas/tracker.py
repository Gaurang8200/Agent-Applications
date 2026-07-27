import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.job import JobPostingOut


class ApplicationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_type: str
    actor: str
    message: str | None
    payload: dict | None
    created_at: datetime


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    job_posting: JobPostingOut
    cover_letter: str | None
    cv_local_path: str | None
    cover_letter_local_path: str | None
    submitted_at: datetime | None
    # Set only when a human approved the submission — the audit trail for the
    # approval gate.
    approved_by_user_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ApplicationDetail(ApplicationOut):
    events: list[ApplicationEventOut] = Field(default_factory=list)


class CreateApplicationRequest(BaseModel):
    # Provide one of these.
    match_id: uuid.UUID | None = None
    job_posting_id: uuid.UUID | None = None


class TransitionRequest(BaseModel):
    status: str
    message: str | None = None


class BoardResponse(BaseModel):
    counts: dict[str, int]
    applications: list[ApplicationOut]
