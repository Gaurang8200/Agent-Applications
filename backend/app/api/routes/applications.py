from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.tailor import tailor
from app.api.deps import get_current_profile
from app.db.session import get_db
from app.models import JobPosting, Profile
from app.schemas.application import PreparedApplication, PrepareRequest
from app.services import application_files, storage
from app.services.pdf import Contact, EducationLine, PdfRenderError, render_anschreiben_pdf, render_cv_pdf

router = APIRouter(prefix="/applications", tags=["applications"])


def _contact(profile: Profile) -> Contact:
    user = profile.user
    name = (user.full_name or user.email.split("@")[0]).strip()
    return Contact(
        name=name,
        email=user.email,
        phone=profile.phone,
        location=profile.location,
        links=profile.links or {},
    )


def _education(profile: Profile) -> list[EducationLine]:
    lines: list[EducationLine] = []
    for ed in sorted(profile.education, key=lambda e: e.display_order):
        bits = [ed.degree, ed.field_of_study, ed.institution]
        label = ", ".join(b for b in bits if b)
        start = ed.start_date.year if ed.start_date else ""
        end = ed.end_date.year if ed.end_date else ""
        dates = " – ".join(str(y) for y in [start, end] if y)
        lines.append(EducationLine(line=label or ed.institution, dates=dates))
    return lines


@router.post("/prepare", response_model=PreparedApplication)
def prepare(
    payload: PrepareRequest,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> PreparedApplication:
    """Tailor to a job and render the CV + Anschreiben into per-company PDFs.

    This is the 'prepare' step of the approval-gated flow — it produces the
    documents you review before submitting. It does not submit anything.
    """
    jd = payload.job_description
    job_title = payload.job_title
    company = payload.company

    if payload.job_posting_id:
        posting = db.scalar(
            select(JobPosting).where(JobPosting.id == payload.job_posting_id)
        )
        if posting is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job posting not found")
        jd = jd or posting.description
        job_title = job_title or posting.title
        company = company or posting.company

    if not jd or not jd.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide a job_description or posting")
    if not company or not company.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Provide a company name — PDFs are saved into a per-company folder",
        )

    try:
        result = tailor(
            profile,
            jd,
            job_title=job_title,
            company=company,
            constraints=payload.constraints,
            sample_anschreiben=payload.sample_anschreiben,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    try:
        cv_pdf = render_cv_pdf(_contact(profile), result.cv, _education(profile))
        letter_pdf = render_anschreiben_pdf(_contact(profile), company, result.anschreiben.body)
    except PdfRenderError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    saved = application_files.save_application(
        user_id=profile.user_id, company=company, cv_pdf=cv_pdf, anschreiben_pdf=letter_pdf
    )

    return PreparedApplication(
        company=company,
        compliant=result.compliant,
        violations=result.violations,
        cv=result.cv,
        anschreiben=result.anschreiben,
        cv_local_path=saved.cv_local_path,
        anschreiben_local_path=saved.anschreiben_local_path,
        cv_url=storage.presigned_url(saved.cv_s3_key),
        anschreiben_url=storage.presigned_url(saved.anschreiben_s3_key),
    )
