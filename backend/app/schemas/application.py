from pydantic import BaseModel

from app.schemas.tailor import RuleViolation, TailoredAnschreiben, TailoredCV, TailorRequest


class PrepareRequest(TailorRequest):
    """Tailor to a job and render the CV + Anschreiben to PDF.

    `company` is required (directly, or via the referenced posting) because the
    PDFs are saved into a per-company folder.
    """

    sample_anschreiben: str | None = None


class PreparedApplication(BaseModel):
    company: str
    compliant: bool
    violations: list[RuleViolation]

    cv: TailoredCV
    anschreiben: TailoredAnschreiben

    # Local file paths on the user's machine, and time-limited download URLs.
    cv_local_path: str
    anschreiben_local_path: str
    cv_url: str
    anschreiben_url: str
