from pathlib import Path

from docx import Document
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models import JobPosting, User
from app.schemas.tailor import RuleViolation
from app.services.docx_prepare import DocxPrepareError, prepare_application

settings = get_settings()
router = APIRouter(prefix="/applications", tags=["applications"])


class DocxPrepareRequest(BaseModel):
    job_posting_id: str | None = None
    job_description: str | None = None
    job_title: str | None = None
    company: str | None = None


class DocxPreparedResponse(BaseModel):
    company: str
    compliant: bool
    violations: list[RuleViolation]
    # Problems found by measuring the rendered PDF (1.75–2.0-line rule).
    # Empty means every bullet verified against the actual output.
    line_problems: list[str]
    subject: str | None
    cv_docx: str
    anschreiben_docx: str
    cv_pdf: str
    anschreiben_pdf: str


def _template(path_str: str, label: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        # Relative paths resolve against the backend working directory.
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{label} template not found at {path}. Set the path in .env.",
        )
    return path


@router.post("/prepare-docx", response_model=DocxPreparedResponse)
def prepare_from_docx(
    payload: DocxPrepareRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocxPreparedResponse:
    """Tailor the user's own .docx CV + Anschreiben to a job and render PDFs.

    Only bullet text, the letter subject, and the letter body change; the
    documents' design, contact details, and structure stay exactly as uploaded.
    Prepares only — nothing is submitted anywhere.
    """
    jd = payload.job_description
    job_title = payload.job_title
    company = payload.company

    if payload.job_posting_id:
        posting = db.scalar(select(JobPosting).where(JobPosting.id == payload.job_posting_id))
        if posting is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job posting not found")
        jd = jd or posting.description
        job_title = job_title or posting.title
        company = company or posting.company

    if not jd or not jd.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide a job_description or posting")
    if not company or not company.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide a company name")

    cv_path = _template(settings.cv_template_path, "CV")
    letter_path = _template(settings.anschreiben_template_path, "Anschreiben")

    try:
        files, result, line_problems = prepare_application(
            cv_template=cv_path,
            anschreiben_template=letter_path,
            job_description=jd,
            job_title=job_title,
            company=company,
        )
    except DocxPrepareError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return DocxPreparedResponse(
        company=files.company,
        compliant=result.compliant and not line_problems,
        violations=result.violations,
        line_problems=line_problems,
        subject=result.anschreiben.subject,
        cv_docx=files.cv_docx,
        anschreiben_docx=files.anschreiben_docx,
        cv_pdf=files.cv_pdf,
        anschreiben_pdf=files.anschreiben_pdf,
    )
