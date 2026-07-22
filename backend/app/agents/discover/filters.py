"""Pure filtering logic for discovered job postings.

All functions here are side-effect free and network free so they can be unit
tested directly. The rules encode the product spec:

- posted within the last N days
- title matches one of the target role keywords
- at least one of the candidate's skills appears in the posting
- company is not on the exclusion list (e.g. SAP)
- required experience does not exceed the cap; postings that mention experience
  without a concrete number are kept (the spec says apply to those)
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Default target roles. Matched case-insensitively as substrings of the title,
# so "Senior Backend Developer" matches "backend".
DEFAULT_ROLE_KEYWORDS = [
    "full stack",
    "fullstack",
    "full-stack",
    "backend",
    "back end",
    "back-end",
    "ai developer",
    "ai engineer",
    "agentic",
    "machine learning",
    "ml engineer",
    "system engineer",
    "systems engineer",
    "software engineer",
    "software developer",
]

DEFAULT_EXCLUDED_COMPANIES = ["sap"]

# Phrases that signal an experience requirement with no fixed number. These are
# kept, per the spec, rather than filtered out.
_UNSPECIFIED_EXPERIENCE = re.compile(
    r"(several years|multiple years|mehrj[aä]hrige|einschl[aä]gige berufserfahrung"
    r"|fundierte berufserfahrung|langj[aä]hrige)",
    re.IGNORECASE,
)

# "3 years", "3+ years", "2-4 years", "at least 3 years", "3 Jahre",
# "mindestens 3 Jahre". Captures the lower-bound number before a years/Jahre unit.
_YEARS_REQUIREMENT = re.compile(
    r"(\d{1,2})\s*(?:\+|-|–|to|bis)?\s*(?:\d{1,2})?\s*\+?\s*(?:years?|yrs?|jahre?n?)",
    re.IGNORECASE,
)


@dataclass
class JobFilterConfig:
    role_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_ROLE_KEYWORDS))
    excluded_companies: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_COMPANIES)
    )
    max_required_years: int = 3
    posted_within_days: int = 7


@dataclass
class FilterDecision:
    keep: bool
    reason: str
    matched_skills: list[str] = field(default_factory=list)


def matches_role(title: str, keywords: list[str]) -> bool:
    low = title.lower()
    return any(keyword in low for keyword in keywords)


def matched_skills(text: str, skills: list[str]) -> list[str]:
    """Skills that appear as whole words/phrases in the posting text.

    Word-boundary matched so "Go" does not match "Django" and "R" does not
    match every capital R.
    """
    low = text.lower()
    found: list[str] = []
    for skill in skills:
        s = skill.strip().lower()
        if not s:
            continue
        # Bound on alphanumerics only, so adjacent punctuation (a trailing "."
        # in "FastAPI.", the "+" inside "C++") does not block a match, while
        # "Go" still won't match inside "Django".
        pattern = r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            found.append(skill)
    return found


def is_excluded_company(company: str, excluded: list[str]) -> bool:
    low = company.lower()
    return any(bad in low for bad in excluded)


def min_required_years(text: str) -> int | None:
    """Smallest concrete years-of-experience requirement found, or None.

    Returns None when the posting states no number, or only vague phrasing like
    "several years" — those are kept per the spec. The lower bound of any range
    is used ("2-4 years" -> 2), and the minimum across all mentions is taken, so
    filtering stays inclusive.
    """
    numbers = [int(m.group(1)) for m in _YEARS_REQUIREMENT.finditer(text)]
    if numbers:
        return min(numbers)
    return None


def is_recent(posted_at: datetime | None, within_days: int, *, now: datetime | None = None) -> bool:
    if posted_at is None:
        # No date on the posting — don't exclude on age we can't measure.
        return True
    now = now or datetime.now(timezone.utc)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    return posted_at >= now - timedelta(days=within_days)


def evaluate(
    *,
    title: str,
    company: str,
    text: str,
    posted_at: datetime | None,
    skills: list[str],
    config: JobFilterConfig,
    now: datetime | None = None,
) -> FilterDecision:
    """Run every rule and return the first failing reason, or keep=True.

    `text` should be title + description + requirements concatenated, so skill
    and experience matching see the whole posting.
    """
    if is_excluded_company(company, config.excluded_companies):
        return FilterDecision(False, f"excluded company: {company}")

    if not is_recent(posted_at, config.posted_within_days, now=now):
        return FilterDecision(False, "older than the recency window")

    if not matches_role(title, config.role_keywords):
        return FilterDecision(False, "title does not match a target role")

    required = min_required_years(text)
    if required is not None and required > config.max_required_years:
        return FilterDecision(False, f"requires {required} years (> {config.max_required_years})")

    found = matched_skills(text, skills)
    if not found:
        return FilterDecision(False, "no candidate skill found in posting")

    return FilterDecision(True, "matched", matched_skills=found)
