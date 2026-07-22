import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobPostingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source: str
    url: str
    title: str
    company: str
    location: str | None
    is_remote: bool
    description: str | None
    posted_at: datetime | None


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    final_score: float
    matched_skills: list[str]
    missing_skills: list[str]
    status: str
    reasoning: str | None
    job_posting: JobPostingOut
    created_at: datetime


class DiscoverRequest(BaseModel):
    # Optional overrides; defaults live in JobFilterConfig.
    role_keywords: list[str] | None = None
    excluded_companies: list[str] | None = None
    max_required_years: int | None = Field(default=None, ge=0, le=20)
    posted_within_days: int | None = Field(default=None, ge=1, le=90)
    max_pages: int = Field(default=3, ge=1, le=10)


class DiscoverResponse(BaseModel):
    scanned: int
    kept: int
    new_postings: int
    new_matches: int
