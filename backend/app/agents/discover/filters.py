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


# Major German cities and every federal state, used to recognise a German
# location from free text when a source gives no country code.
GERMAN_PLACES = {
    "germany", "deutschland", "allemagne",
    "baden-württemberg", "baden-wuerttemberg", "bayern", "bavaria", "berlin",
    "brandenburg", "bremen", "hamburg", "hessen", "hesse",
    "mecklenburg-vorpommern", "niedersachsen", "lower saxony",
    "nordrhein-westfalen", "north rhine-westphalia", "nrw",
    "rheinland-pfalz", "rhineland-palatinate", "saarland", "sachsen", "saxony",
    "sachsen-anhalt", "saxony-anhalt", "schleswig-holstein", "thüringen",
    "thuringia",
    "münchen", "munich", "muenchen", "köln", "cologne", "koeln", "frankfurt",
    "stuttgart", "düsseldorf", "dusseldorf", "duesseldorf", "dortmund", "essen",
    "leipzig", "dresden", "hannover", "hanover", "nürnberg", "nuremberg",
    "nuernberg", "duisburg", "bochum", "wuppertal", "bielefeld", "bonn",
    "mannheim", "karlsruhe", "wiesbaden", "münster", "muenster", "augsburg",
    "aachen", "mönchengladbach", "gelsenkirchen", "braunschweig", "kiel",
    "chemnitz", "halle", "magdeburg", "freiburg", "krefeld", "mainz", "lübeck",
    "luebeck", "erfurt", "rostock", "kassel", "potsdam", "saarbrücken",
    "saarbruecken", "heidelberg", "darmstadt", "regensburg", "ingolstadt",
    "würzburg", "wuerzburg", "wolfsburg", "ulm", "heilbronn", "pforzheim",
    "göttingen", "goettingen", "bottrop", "reutlingen", "koblenz", "jena",
    "erlangen", "trier", "siegen", "hildesheim", "salzgitter", "cottbus",
    "gütersloh", "guetersloh", "kaiserslautern", "schwerin", "esslingen",
    "ludwigshafen", "oberhausen", "hagen", "hamm", "leverkusen", "solingen",
    "neuss", "paderborn", "offenbach", "fürth", "fuerth", "remscheid",
}

# Places that read as German-adjacent but are not in Germany — guards against
# a naive substring match on shared names.
NON_GERMAN_PLACES = {
    "vienna", "wien", "austria", "österreich", "zurich", "zürich", "basel",
    "geneva", "switzerland", "schweiz", "london", "uk", "united kingdom",
    "amsterdam", "netherlands", "paris", "france", "madrid", "spain",
    "warsaw", "poland", "prague", "czech", "lisbon", "portugal", "dublin",
    "ireland", "stockholm", "sweden", "copenhagen", "denmark", "milan",
    "italy", "brussels", "belgium", "luxembourg", "new york", "san francisco",
    "usa", "united states", "canada", "india", "singapore", "australia",
}


@dataclass
class JobFilterConfig:
    role_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_ROLE_KEYWORDS))
    excluded_companies: list[str] = field(
        default_factory=lambda: list(DEFAULT_EXCLUDED_COMPANIES)
    )
    max_required_years: int = 3
    posted_within_days: int = 7
    # Only keep postings located in Germany.
    germany_only: bool = True


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


def _mentions(text: str, places: set[str]) -> bool:
    low = text.lower()
    return any(
        re.search(r"(?<![a-zäöüß])" + re.escape(p) + r"(?![a-zäöüß])", low)
        for p in places
    )


def is_in_germany(location: str | None, country: str | None) -> bool:
    """Decide whether a posting is located in Germany.

    An explicit country code from the source wins. Otherwise the location text
    is matched against German places, with a guard for nearby countries whose
    names would otherwise slip through. A posting with no location at all is
    rejected — an unplaceable role is not worth an application.
    """
    if country:
        return country.upper() in {"DE", "DEU", "GERMANY"}
    if not location:
        return False
    if _mentions(location, NON_GERMAN_PLACES):
        return False
    return _mentions(location, GERMAN_PLACES)


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
    location: str | None = None,
    country: str | None = None,
) -> FilterDecision:
    """Run every rule and return the first failing reason, or keep=True.

    `text` should be title + description + requirements concatenated, so skill
    and experience matching see the whole posting.
    """
    if config.germany_only and not is_in_germany(location, country):
        return FilterDecision(False, f"not located in Germany: {location or 'unknown'}")

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
