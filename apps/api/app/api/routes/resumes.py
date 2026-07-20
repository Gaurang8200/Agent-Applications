from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.resume_parser import parse_resume
from app.api.deps import get_current_profile
from app.db.session import get_db
from app.models import Profile, Resume
from app.schemas.profile import ParsedResume, ResumeOut, ResumeUploadResponse
from app.services import storage
from app.services.text_extraction import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_CONTENT_TYPES,
    TextExtractionError,
    UnsupportedFileType,
    extract_text,
)

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.post("", response_model=ResumeUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_resume(
    file: UploadFile = File(...),
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> ResumeUploadResponse:
    if file.content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Upload a PDF, DOCX, or TXT file. Got: {file.content_type}",
        )

    data = file.file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
        )
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

    key = storage.build_key(profile.user_id, file.filename or "resume")
    storage.upload_bytes(key, data, file.content_type)

    resume = Resume(
        profile_id=profile.id,
        filename=file.filename or "resume",
        content_type=file.content_type,
        size_bytes=len(data),
        s3_key=key,
        # First upload becomes the primary resume by default.
        is_primary=not profile.resumes,
    )
    db.add(resume)
    db.flush()

    parsed: ParsedResume | None = None
    try:
        resume.raw_text = extract_text(data, file.content_type)
        parsed = parse_resume(resume.raw_text)
        resume.parsed_payload = parsed.model_dump(mode="json")
        resume.parse_status = "parsed"
    except (UnsupportedFileType, TextExtractionError) as exc:
        # The upload itself succeeded; surface the parse failure without losing
        # the stored file so the user can retry parsing later.
        resume.parse_status = "failed"
        resume.parse_error = str(exc)
    except Exception as exc:  # noqa: BLE001 - record any extractor failure
        resume.parse_status = "failed"
        resume.parse_error = f"Unexpected parsing error: {exc}"

    db.commit()
    db.refresh(resume)

    return ResumeUploadResponse(resume=ResumeOut.model_validate(resume), parsed=parsed)


@router.get("", response_model=list[ResumeOut])
def list_resumes(
    profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)
) -> list[Resume]:
    return list(
        db.scalars(
            select(Resume)
            .where(Resume.profile_id == profile.id)
            .order_by(Resume.created_at.desc())
        )
    )


@router.get("/{resume_id}/download")
def download_url(
    resume_id: str,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    resume = db.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.profile_id == profile.id)
    )
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return {"url": storage.presigned_url(resume.s3_key)}
