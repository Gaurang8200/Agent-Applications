"""Persist generated application PDFs: locally per company, and to object storage.

Local copies land under `settings.applications_path/<Company>/` so the user has
the files on disk, as specified. The same bytes go to MinIO/S3 so the app can
serve them back later.
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.services import storage

settings = get_settings()

# Keep only filesystem-safe characters in a company folder name.
_SAFE = re.compile(r"[^A-Za-z0-9 ._-]+")


def safe_company_name(company: str) -> str:
    cleaned = _SAFE.sub("", company).strip().strip(".")
    return cleaned or "Unknown Company"


@dataclass
class SavedApplication:
    company: str
    cv_local_path: str
    anschreiben_local_path: str
    cv_s3_key: str
    anschreiben_s3_key: str


def _write_local(company_dir: Path, filename: str, data: bytes) -> str:
    company_dir.mkdir(parents=True, exist_ok=True)
    path = company_dir / filename
    path.write_bytes(data)
    return str(path)


def save_application(
    *,
    user_id: uuid.UUID,
    company: str,
    cv_pdf: bytes,
    anschreiben_pdf: bytes,
) -> SavedApplication:
    safe = safe_company_name(company)
    company_dir = settings.applications_path / safe
    cv_name = f"CV_{safe}.pdf".replace(" ", "_")
    letter_name = f"Anschreiben_{safe}.pdf".replace(" ", "_")

    cv_local = _write_local(company_dir, cv_name, cv_pdf)
    letter_local = _write_local(company_dir, letter_name, anschreiben_pdf)

    prefix = f"applications/{user_id}/{safe}"
    cv_key = storage.upload_bytes(f"{prefix}/{cv_name}", cv_pdf, "application/pdf")
    letter_key = storage.upload_bytes(
        f"{prefix}/{letter_name}", anschreiben_pdf, "application/pdf"
    )

    return SavedApplication(
        company=company,
        cv_local_path=cv_local,
        anschreiben_local_path=letter_local,
        cv_s3_key=cv_key,
        anschreiben_s3_key=letter_key,
    )
