"""Tests for PDF rendering and the per-company file naming.

The render tests need WeasyPrint's native libraries (pango/cairo). Where those
aren't loadable (e.g. CI without the system packages), the render tests skip
rather than fail; the naming test is pure and always runs.
"""

import pytest

from app.schemas.tailor import TailoredCV, TailoredExperience
from app.services.application_files import safe_company_name
from app.services.pdf import (
    Contact,
    EducationLine,
    PdfRenderError,
    render_anschreiben_pdf,
    render_cv_pdf,
)


def _sample_cv() -> TailoredCV:
    long_bullet = (
        "Rebuilt the billing pipeline into an event driven service that cut "
        "invoice latency from several hours down to a few minutes for finance"
    )
    return TailoredCV(
        headline="Backend Engineer",
        summary="Backend engineer focused on distributed systems.",
        skills=["Python", "Go", "PostgreSQL"],
        experiences=[
            TailoredExperience(
                company="Acme Cloud",
                title="Senior Backend Engineer",
                start_date="2023-03-01",
                is_current=True,
                bullets=[long_bullet] * 6,
            ),
            TailoredExperience(
                company="DataForge",
                title="Backend Engineer",
                start_date="2020-06-01",
                end_date="2023-02-01",
                bullets=[long_bullet] * 4,
            ),
        ],
    )


CONTACT = Contact(
    name="Test Candidate",
    email="test@example.com",
    phone="+49 151 000",
    location="Berlin",
    links={"github": "github.com/test"},
)


def _render_or_skip(fn, *args):
    try:
        return fn(*args)
    except PdfRenderError as exc:
        if "native librar" in str(exc):
            pytest.skip(f"WeasyPrint native libs unavailable: {exc}")
        raise


def test_safe_company_name():
    assert safe_company_name("SAP SE") == "SAP SE"
    assert safe_company_name("Foo/Bar GmbH & Co.") == "FooBar GmbH  Co"
    assert safe_company_name("///") == "Unknown Company"
    assert safe_company_name("   ") == "Unknown Company"


def test_cv_renders_single_page_pdf():
    pdf = _render_or_skip(render_cv_pdf, CONTACT, _sample_cv(), [
        EducationLine(line="BEng Computer Engineering, GTU", dates="2016 – 2020")
    ])
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_anschreiben_renders_pdf():
    body = (
        "Sehr geehrtes Team,\n\n"
        "die Rolle passt zu meiner Erfahrung mit verteilten Systemen.\n\n"
        "Ich freue mich auf ein Gespraech."
    )
    pdf = _render_or_skip(render_anschreiben_pdf, CONTACT, "Zalando", body)
    assert pdf.startswith(b"%PDF")


def test_cv_over_one_page_raises():
    cv = _sample_cv()
    # Force overflow: a huge summary that cannot fit on one page.
    cv.summary = "This is a very long summary sentence. " * 200
    with pytest.raises(PdfRenderError) as exc:
        render_cv_pdf(CONTACT, cv, [])
    # Either overflow or (on a machine without libs) the native-lib skip.
    if "native librar" in str(exc.value):
        pytest.skip("WeasyPrint native libs unavailable")
    assert "one page" in str(exc.value)
