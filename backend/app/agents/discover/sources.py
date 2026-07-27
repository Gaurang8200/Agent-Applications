"""Job-board source adapters.

Each adapter fetches from a documented public API and normalizes to
`NormalizedPosting`. Only APIs the operator publishes for programmatic use are
used — no scraping of sites that forbid it, and no LinkedIn, which offers no
public jobs API and prohibits scraping.

Coverage is deliberately split. The federal agency carries a very large volume
of German postings, mostly small and mid-size employers. Large firms publish
through their own applicant tracking systems, so Greenhouse, Lever, and
SmartRecruiters adapters reach them directly.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

import httpx


@dataclass
class NormalizedPosting:
    source: str
    external_id: str
    url: str
    title: str
    company: str
    location: str | None
    is_remote: bool
    description: str
    tags: list[str] = field(default_factory=list)
    posted_at: datetime | None = None
    # ISO country code where known. Sources that only serve one country set it
    # directly; others derive it from the posting's location payload.
    country: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        """Everything a filter should see: title, description, tags."""
        return "\n".join([self.title, self.description, " ".join(self.tags)])


class JobSource(Protocol):
    name: str

    def fetch(self, *, within_days: int, max_pages: int) -> list[NormalizedPosting]:
        """Return recent postings. Sources push `within_days` into the query
        where their API supports it, and ignore it otherwise — the filter layer
        enforces recency regardless."""


_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")


def _strip_html(html: str) -> str:
    text = _HTML_TAG.sub(" ", html or "")
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(entity, char)
    return _WS.sub(" ", text).strip()


class ArbeitnowSource:
    """Berlin-based board. Broad but not Germany-exclusive, so postings carry
    no country and are filtered by their location text downstream."""

    name = "arbeitnow"
    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    def fetch(self, *, within_days: int = 7, max_pages: int = 3) -> list[NormalizedPosting]:
        postings: list[NormalizedPosting] = []
        with httpx.Client(timeout=self._timeout) as client:
            url = self.BASE_URL
            for _ in range(max_pages):
                response = client.get(url)
                response.raise_for_status()
                body = response.json()
                for item in body.get("data", []):
                    postings.append(self._normalize(item))
                url = (body.get("links") or {}).get("next")
                if not url:
                    break
        return postings

    def _normalize(self, item: dict) -> NormalizedPosting:
        created = item.get("created_at")
        posted_at = (
            datetime.fromtimestamp(created, tz=timezone.utc)
            if isinstance(created, (int, float))
            else None
        )
        return NormalizedPosting(
            source=self.name,
            external_id=str(item.get("slug") or item.get("url") or ""),
            url=item.get("url", ""),
            title=item.get("title", ""),
            company=item.get("company_name", ""),
            location=item.get("location"),
            is_remote=bool(item.get("remote")),
            description=_strip_html(item.get("description", "")),
            tags=list(item.get("tags") or []) + list(item.get("job_types") or []),
            posted_at=posted_at,
            raw=item,
        )


class ArbeitsagenturSource:
    """The German federal employment agency's job search.

    Every posting is in Germany by definition, and the API accepts both a
    recency window and free-text role queries, so filtering happens upstream
    rather than after download.
    """

    name = "arbeitsagentur"
    BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
    # Public client key published for the job-search API; not a secret.
    API_KEY = "jobboerse-jobsuche"

    DEFAULT_QUERIES = [
        "Software Entwickler",
        "Backend Entwickler",
        "Full Stack Entwickler",
        "DevOps Engineer",
        "Machine Learning Engineer",
        "KI Entwickler",
        "Data Engineer",
    ]

    def __init__(self, queries: list[str] | None = None, timeout: float = 25.0) -> None:
        self.queries = queries or list(self.DEFAULT_QUERIES)
        self._timeout = timeout

    def fetch(self, *, within_days: int = 7, max_pages: int = 2) -> list[NormalizedPosting]:
        postings: list[NormalizedPosting] = []
        seen: set[str] = set()
        headers = {"X-API-Key": self.API_KEY}

        with httpx.Client(timeout=self._timeout, headers=headers) as client:
            for query in self.queries:
                for page in range(1, max_pages + 1):
                    response = client.get(
                        self.BASE_URL,
                        params={
                            "was": query,
                            "veroeffentlichtseit": within_days,
                            "size": 50,
                            "page": page,
                        },
                    )
                    if response.status_code == 404:
                        break  # no results for this query
                    response.raise_for_status()
                    items = response.json().get("stellenangebote") or []
                    if not items:
                        break
                    for item in items:
                        posting = self._normalize(item)
                        # The same posting surfaces under several role queries.
                        if posting.external_id and posting.external_id not in seen:
                            seen.add(posting.external_id)
                            postings.append(posting)
        return postings

    def _normalize(self, item: dict) -> NormalizedPosting:
        place = item.get("arbeitsort") or {}
        city = place.get("ort")
        region = place.get("region")
        location = ", ".join(p for p in (city, region) if p) or "Deutschland"

        posted_at = None
        raw_date = item.get("aktuelleVeroeffentlichungsdatum")
        if raw_date:
            try:
                posted_at = datetime.fromisoformat(raw_date).replace(tzinfo=timezone.utc)
            except ValueError:
                posted_at = None

        ref = item.get("refnr", "")
        return NormalizedPosting(
            source=self.name,
            external_id=ref,
            # The agency's own detail page; stable and public.
            url=item.get("externeUrl")
            or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
            title=item.get("titel") or item.get("beruf", ""),
            company=item.get("arbeitgeber", ""),
            location=location,
            is_remote=False,
            # The list endpoint returns no description; the role title and
            # occupation classification are what we match on.
            description=" ".join(
                p for p in (item.get("titel"), item.get("beruf")) if p
            ),
            tags=[item["beruf"]] if item.get("beruf") else [],
            posted_at=posted_at,
            country="DE",
            raw=item,
        )


class GreenhouseSource:
    """Greenhouse public job boards, one board token per company."""

    name = "greenhouse"
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    def __init__(self, tokens: list[str], timeout: float = 20.0) -> None:
        self.tokens = tokens
        self._timeout = timeout

    def fetch(self, *, within_days: int = 7, max_pages: int = 1) -> list[NormalizedPosting]:
        postings: list[NormalizedPosting] = []
        with httpx.Client(timeout=self._timeout) as client:
            for token in self.tokens:
                try:
                    response = client.get(
                        self.BASE_URL.format(token=token), params={"content": "true"}
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    # A retired board token must not take down the whole run.
                    continue
                for item in response.json().get("jobs", []):
                    postings.append(self._normalize(token, item))
        return postings

    def _normalize(self, token: str, item: dict) -> NormalizedPosting:
        posted_at = None
        raw_date = item.get("updated_at") or item.get("first_published")
        if raw_date:
            try:
                posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        location = (item.get("location") or {}).get("name")
        return NormalizedPosting(
            source=self.name,
            external_id=f"{token}:{item.get('id')}",
            url=item.get("absolute_url", ""),
            title=item.get("title", ""),
            # Greenhouse boards are per-company; the token is the company.
            company=(item.get("company_name") or token).replace("-", " ").title(),
            location=location,
            is_remote=bool(location and "remote" in location.lower()),
            description=_strip_html(item.get("content", "")),
            tags=[d.get("name", "") for d in item.get("departments", [])],
            posted_at=posted_at,
            raw=item,
        )


class LeverSource:
    """Lever public postings, one company handle per board."""

    name = "lever"
    BASE_URL = "https://api.lever.co/v0/postings/{handle}"

    def __init__(self, handles: list[str], timeout: float = 20.0) -> None:
        self.handles = handles
        self._timeout = timeout

    def fetch(self, *, within_days: int = 7, max_pages: int = 1) -> list[NormalizedPosting]:
        postings: list[NormalizedPosting] = []
        with httpx.Client(timeout=self._timeout) as client:
            for handle in self.handles:
                try:
                    response = client.get(
                        self.BASE_URL.format(handle=handle), params={"mode": "json"}
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    continue
                for item in response.json():
                    postings.append(self._normalize(handle, item))
        return postings

    def _normalize(self, handle: str, item: dict) -> NormalizedPosting:
        created = item.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            if isinstance(created, (int, float))
            else None
        )
        categories = item.get("categories") or {}
        location = categories.get("location")
        return NormalizedPosting(
            source=self.name,
            external_id=f"{handle}:{item.get('id')}",
            url=item.get("hostedUrl", ""),
            title=item.get("text", ""),
            company=handle.replace("-", " ").title(),
            location=location,
            is_remote=bool(location and "remote" in location.lower()),
            description=_strip_html(item.get("descriptionPlain") or item.get("description", "")),
            tags=[v for v in (categories.get("team"), categories.get("department")) if v],
            posted_at=posted_at,
            raw=item,
        )


class SmartRecruitersSource:
    """SmartRecruiters public postings, filtered to Germany at the API."""

    name = "smartrecruiters"
    BASE_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings"

    def __init__(self, companies: list[str], timeout: float = 20.0) -> None:
        self.companies = companies
        self._timeout = timeout

    def fetch(self, *, within_days: int = 7, max_pages: int = 2) -> list[NormalizedPosting]:
        postings: list[NormalizedPosting] = []
        with httpx.Client(timeout=self._timeout) as client:
            for company in self.companies:
                for page in range(max_pages):
                    try:
                        response = client.get(
                            self.BASE_URL.format(company=company),
                            params={"country": "de", "limit": 100, "offset": page * 100},
                        )
                        response.raise_for_status()
                    except httpx.HTTPError:
                        break
                    items = response.json().get("content", [])
                    if not items:
                        break
                    for item in items:
                        postings.append(self._normalize(company, item))
        return postings

    def _normalize(self, company: str, item: dict) -> NormalizedPosting:
        posted_at = None
        raw_date = item.get("releasedDate")
        if raw_date:
            try:
                posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        place = item.get("location") or {}
        city = place.get("city")
        return NormalizedPosting(
            source=self.name,
            external_id=f"{company}:{item.get('id')}",
            url=f"https://jobs.smartrecruiters.com/{company}/{item.get('id')}",
            title=item.get("name", ""),
            company=(item.get("company") or {}).get("name") or company,
            location=city,
            is_remote=bool(place.get("remote")),
            # The list endpoint omits the body; the title and function carry
            # enough signal for skill matching.
            description=" ".join(
                p
                for p in (item.get("name"), (item.get("function") or {}).get("label"))
                if p
            ),
            tags=[
                v
                for v in (
                    (item.get("function") or {}).get("label"),
                    (item.get("industry") or {}).get("label"),
                )
                if v
            ],
            posted_at=posted_at,
            country=(place.get("country") or "de").upper(),
            raw=item,
        )
