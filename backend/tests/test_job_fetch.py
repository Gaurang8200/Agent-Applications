"""Tests for the pasted-link job fetcher (pure parsing, no network)."""

import pytest

from app.services.job_fetch import JobFetchError, _html_to_text, _title_of


def test_html_reduced_to_readable_text():
    html = """<html><head><title>Backend Engineer - Acme</title>
    <script>var x=1;</script><style>.a{}</style></head>
    <body><nav>menu</nav><h1>Backend Engineer</h1>
    <p>We build with Python &amp; Go in M&uuml;nchen.</p>
    <li>FastAPI</li><li>PostgreSQL</li><footer>legal</footer></body></html>"""
    text = _html_to_text(html)
    assert "Backend Engineer" in text
    assert "Python & Go in München" in text
    assert "FastAPI" in text
    assert "var x=1" not in text  # script dropped
    assert "menu" not in text  # nav dropped


def test_title_extracted():
    assert _title_of("<title>Senior Dev (m/w/d)</title>") == "Senior Dev (m/w/d)"
    assert _title_of("<p>no title</p>") is None


def test_invalid_url_rejected():
    from app.services.job_fetch import fetch_job_posting

    with pytest.raises(JobFetchError, match="valid http"):
        fetch_job_posting("not-a-url")
    with pytest.raises(JobFetchError, match="valid http"):
        fetch_job_posting("ftp://example.com/job")
