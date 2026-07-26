"""Render a tailored CV and Anschreiben to one-page PDFs.

Uses Jinja2 for the fixed layout and WeasyPrint for HTML -> PDF. The templates
own the structure; the tailored text just fills it, so the CV shape never
changes between jobs.

macOS note: WeasyPrint loads pango/cairo via the dynamic linker. If import
fails with a library error, the server must run with
DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib (wired into .claude/launch.json
and documented in CLAUDE.md). On Linux/Docker the apt libs resolve normally.
"""

from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas.tailor import TailoredCV

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


@dataclass
class Contact:
    name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: dict[str, str] = field(default_factory=dict)

    @property
    def line(self) -> str:
        parts = [self.email, self.phone, self.location, *self.links.values()]
        return "  |  ".join(p for p in parts if p)


@dataclass
class EducationLine:
    line: str
    dates: str


class PdfRenderError(RuntimeError):
    pass


def _import_weasyprint():
    try:
        from weasyprint import HTML  # imported lazily; heavy + has native deps
    except OSError as exc:  # native library load failure
        raise PdfRenderError(
            "WeasyPrint could not load its native libraries. On macOS run the "
            "API with DYLD_FALLBACK_LIBRARY_PATH set to the Homebrew lib dir "
            f"(brew install pango). Original error: {exc}"
        ) from exc
    return HTML


def _experience_view(cv: TailoredCV) -> list[dict]:
    view = []
    for exp in cv.experiences:
        end = "Present" if exp.is_current else (exp.end_date or "")
        dates = " – ".join(p for p in [exp.start_date or "", end] if p)
        view.append(
            {
                "title": exp.title,
                "company": exp.company,
                "dates": dates,
                "bullets": exp.bullets,
            }
        )
    return view


def _render(html: str) -> bytes:
    HTML = _import_weasyprint()
    document = HTML(string=html).render()
    if len(document.pages) > 1:
        # The tailor stage sizes content to one page, but a very long summary or
        # oversized bullets can still spill. Surface it rather than ship page 2.
        raise PdfRenderError(
            f"Rendered to {len(document.pages)} pages; content exceeds one page."
        )
    return document.write_pdf()


def render_cv_pdf(
    contact: Contact,
    cv: TailoredCV,
    education: list[EducationLine] | None = None,
) -> bytes:
    html = _env.get_template("cv.html").render(
        contact=contact,
        cv={
            "headline": cv.headline,
            "summary": cv.summary,
            "skills": cv.skills,
            "experiences": _experience_view(cv),
        },
        education=[e.__dict__ for e in (education or [])],
    )
    return _render(html)


def render_anschreiben_pdf(contact: Contact, company: str | None, body: str) -> bytes:
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    html = _env.get_template("anschreiben.html").render(
        contact=contact, company=company, paragraphs=paragraphs
    )
    return _render(html)
