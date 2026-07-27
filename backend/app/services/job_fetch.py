"""Fetch a job description from a URL the user pastes.

Covers every employer regardless of which system hosts the posting: the user
pastes the link, we fetch the public page and reduce it to readable text for
the tailor stage. Sites that require a login (LinkedIn does for most postings)
cannot be fetched — the caller gets a clear error and can paste the description
text instead.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

_UA = "AgentApplications/0.1 (personal job application assistant)"

_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|nav|header|footer|svg|iframe)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
_BLANK = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]{2,}")

# Pages that came back but are clearly a login/consent wall, not a posting.
_WALL_MARKERS = (
    "sign in to view",
    "join linkedin",
    "log in to continue",
    "enable javascript and cookies",
    "access denied",
)


class JobFetchError(RuntimeError):
    pass


@dataclass
class FetchedJob:
    url: str
    text: str
    title: str | None
    company_hint: str | None


def _html_to_text(html: str) -> str:
    text = _DROP_BLOCKS.sub(" ", html)
    # Preserve block structure enough for the model to see sections.
    text = re.sub(r"</(p|div|li|h[1-6]|tr|br)>", "\n", text, flags=re.IGNORECASE)
    text = _TAG.sub(" ", text)
    for entity, char in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&auml;", "ä"), ("&ouml;", "ö"),
        ("&uuml;", "ü"), ("&szlig;", "ß"), ("&Auml;", "Ä"), ("&Ouml;", "Ö"),
        ("&Uuml;", "Ü"),
    ):
        text = text.replace(entity, char)
    lines = [_SPACES.sub(" ", line).strip() for line in text.splitlines()]
    return _BLANK.sub("\n\n", "\n".join(line for line in lines if line)).strip()


def _title_of(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return _SPACES.sub(" ", _TAG.sub("", match.group(1))).strip()[:200] or None


def fetch_job_posting(url: str) -> FetchedJob:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise JobFetchError("That does not look like a valid http(s) link.")

    try:
        with httpx.Client(
            timeout=25.0, follow_redirects=True, headers={"User-Agent": _UA}
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise JobFetchError(f"Could not fetch the page: {exc}") from exc

    if response.status_code in (401, 403, 999):
        raise JobFetchError(
            "The site refused the request (it likely requires a login, as "
            "LinkedIn does). Paste the job description text instead."
        )
    if response.status_code >= 400:
        raise JobFetchError(f"The page returned HTTP {response.status_code}.")

    text = _html_to_text(response.text)
    low = text.lower()
    if any(marker in low for marker in _WALL_MARKERS):
        raise JobFetchError(
            "The page is behind a login or consent wall. Open the posting in "
            "your browser and paste the description text instead."
        )
    if len(text) < 200:
        raise JobFetchError(
            "Could not extract a readable job description from that page. "
            "Paste the description text instead."
        )

    host = parsed.netloc.removeprefix("www.")
    company_hint = host.split(".")[0].replace("-", " ").title()
    # Keep the tailor prompt bounded; requirements sit early on job pages.
    return FetchedJob(
        url=url, text=text[:12000], title=_title_of(response.text), company_hint=company_hint
    )
