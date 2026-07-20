"""Import every model here so Alembic autogenerate sees the full metadata."""

from app.models.application import Application, ApplicationEvent
from app.models.job import JobPosting, Match
from app.models.profile import Education, Profile, Resume, Skill, WorkExperience
from app.models.user import User

__all__ = [
    "Application",
    "ApplicationEvent",
    "Education",
    "JobPosting",
    "Match",
    "Profile",
    "Resume",
    "Skill",
    "User",
    "WorkExperience",
]
