"""Job-board source adapters.

Each adapter fetches postings from a documented public API and normalizes them
to `NormalizedPosting`. We only use APIs that publish a job feed for
programmatic use — no scraping of sites that forbid it.

Arbeitnow is the default because its board is Germany-focused and its job-board
API needs no key, so discovery works out of the box.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    raw: dict = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        """Everything a filter should see: title, description, tags."""
        return "\n".join([self.title, self.description, " ".join(self.tags)])


_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    return _HTML_TAG.sub(" ", html or "").replace("&nbsp;", " ").strip()


class ArbeitnowSource:
    name = "arbeitnow"
    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout

    def fetch(self, max_pages: int = 3) -> list[NormalizedPosting]:
        postings: list[NormalizedPosting] = []
        with httpx.Client(timeout=self._timeout) as client:
            url = self.BASE_URL
            for _ in range(max_pages):
                response = client.get(url)
                response.raise_for_status()
                body = response.json()
                for item in body.get("data", []):
                    postings.append(self._normalize(item))
                # The API paginates via links.next; stop when absent.
                url = (body.get("links") or {}).get("next")
                if not url:
                    break
        return postings

    def _normalize(self, item: dict) -> NormalizedPosting:
        created = item.get("created_at")
        posted_at = None
        if isinstance(created, (int, float)):
            posted_at = datetime.fromtimestamp(created, tz=timezone.utc)

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
