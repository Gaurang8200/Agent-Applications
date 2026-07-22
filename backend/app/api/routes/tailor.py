from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.tailor import tailor
from app.api.deps import get_current_profile
from app.db.session import get_db
from app.models import JobPosting, Profile
from app.schemas.tailor import TailorRequest, TailorResult

router = APIRouter(prefix="/tailor", tags=["tailor"])


@router.post("", response_model=TailorResult)
def tailor_application(
    payload: TailorRequest,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> TailorResult:
    """Tailor the profile's real experience to a job description.

    Accepts a stored `job_posting_id` or raw `job_description` text. Output is a
    draft for review — it is not submitted anywhere.
    """
    jd = payload.job_description
    job_title = payload.job_title
    company = payload.company

    if payload.job_posting_id:
        posting = db.scalar(
            select(JobPosting).where(JobPosting.id == payload.job_posting_id)
        )
        if posting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Job posting not found"
            )
        jd = jd or posting.description
        job_title = job_title or posting.title
        company = company or posting.company

    if not jd or not jd.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a job_description or a job_posting_id with a description",
        )

    try:
        return tailor(
            profile,
            jd,
            job_title=job_title,
            company=company,
            constraints=payload.constraints,
        )
    except (RuntimeError, ValueError) as exc:
        # RuntimeError: no API key or safety decline. ValueError: empty profile.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
