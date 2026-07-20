from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_profile
from app.db.session import get_db
from app.models import Education, Profile, Resume, Skill, WorkExperience
from app.schemas.profile import ParsedResume, ProfileIn, ProfileOut

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
def read_profile(profile: Profile = Depends(get_current_profile)) -> Profile:
    return profile


@router.patch("", response_model=ProfileOut)
def update_profile(
    payload: ProfileIn,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> Profile:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/apply-parsed/{resume_id}", response_model=ProfileOut)
def apply_parsed_resume(
    resume_id: str,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> Profile:
    """Promote a parsed resume into the profile, replacing prior history.

    Destructive by design: the profile is one canonical record, and merging two
    extractions produces duplicates. The user reviews the parsed draft in the UI
    before calling this.
    """
    resume = db.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.profile_id == profile.id)
    )
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    if not resume.parsed_payload:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Resume has no parsed data (status: {resume.parse_status})",
        )

    parsed = ParsedResume.model_validate(resume.parsed_payload)

    profile.headline = parsed.headline or profile.headline
    profile.summary = parsed.summary or profile.summary
    profile.location = parsed.location or profile.location
    profile.phone = parsed.phone or profile.phone
    if parsed.links:
        profile.links = {**(profile.links or {}), **parsed.links}

    profile.work_experience.clear()
    profile.education.clear()
    profile.skills.clear()
    db.flush()

    for role in parsed.work_experience:
        profile.work_experience.append(WorkExperience(**role.model_dump()))
    for school in parsed.education:
        profile.education.append(Education(**school.model_dump()))
    for skill in parsed.skills:
        profile.skills.append(Skill(**skill.model_dump()))

    db.commit()
    db.refresh(profile)
    return profile
