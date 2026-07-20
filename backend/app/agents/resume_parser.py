"""Turn raw resume text into a structured profile.

Two paths: Claude-backed extraction when an API key is configured, and a
heuristic fallback so the ingest flow works end-to-end before the user has a
key. Either way the result is a draft — the user reviews and edits it before it
becomes their profile.
"""

import json
import re
from datetime import date

import anthropic

from app.core.config import get_settings
from app.schemas.profile import (
    EducationIn,
    ParsedResume,
    SkillIn,
    WorkExperienceIn,
)

settings = get_settings()

SYSTEM_PROMPT = """You extract structured data from resumes.

Rules that matter more than completeness:
- Only output what the resume actually says. Never infer, embellish, or invent \
a title, date, employer, or accomplishment.
- Copy each bullet point into `highlights` close to verbatim. Light cleanup of \
formatting artifacts is fine; rewriting the claim is not.
- Use null for anything genuinely absent rather than guessing a plausible value.
- Dates are ISO 8601 (YYYY-MM-DD). When only a month and year are given, use the \
first of that month. When only a year is given, use January 1st.
- Set `is_current` true only when the resume marks the role as ongoing."""

RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name": {"type": ["string", "null"]},
        "email": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "headline": {
            "type": ["string", "null"],
            "description": "Professional title line, e.g. 'Senior Backend Engineer'",
        },
        "summary": {"type": ["string", "null"]},
        "links": {
            "type": "object",
            "description": "Keys such as linkedin, github, portfolio",
            "additionalProperties": {"type": "string"},
        },
        "work_experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "location": {"type": ["string", "null"]},
                    "start_date": {"type": ["string", "null"], "format": "date"},
                    "end_date": {"type": ["string", "null"], "format": "date"},
                    "is_current": {"type": "boolean"},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "company",
                    "title",
                    "location",
                    "start_date",
                    "end_date",
                    "is_current",
                    "highlights",
                ],
                "additionalProperties": False,
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": "string"},
                    "degree": {"type": ["string", "null"]},
                    "field_of_study": {"type": ["string", "null"]},
                    "start_date": {"type": ["string", "null"], "format": "date"},
                    "end_date": {"type": ["string", "null"], "format": "date"},
                    "grade": {"type": ["string", "null"]},
                },
                "required": [
                    "institution",
                    "degree",
                    "field_of_study",
                    "start_date",
                    "end_date",
                    "grade",
                ],
                "additionalProperties": False,
            },
        },
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {
                        "type": ["string", "null"],
                        "description": "e.g. language, framework, tool, soft",
                    },
                },
                "required": ["name", "category"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "full_name",
        "email",
        "phone",
        "location",
        "headline",
        "summary",
        "links",
        "work_experience",
        "education",
        "skills",
    ],
    "additionalProperties": False,
}


def parse_resume(raw_text: str) -> ParsedResume:
    """Parse resume text, preferring Claude and falling back to heuristics."""
    if settings.llm_enabled:
        return _parse_with_claude(raw_text)
    return _parse_heuristically(raw_text)


def _parse_with_claude(raw_text: str) -> ParsedResume:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": RESUME_SCHEMA},
        },
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Extract the structured profile from this resume:\n\n{raw_text}",
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Resume extraction was declined by the safety system.")

    text = next(b.text for b in response.content if b.type == "text")
    payload = json.loads(text)

    parsed = ParsedResume(
        full_name=payload.get("full_name"),
        email=payload.get("email"),
        phone=payload.get("phone"),
        location=payload.get("location"),
        headline=payload.get("headline"),
        summary=payload.get("summary"),
        links=payload.get("links") or {},
        extraction_method="llm",
    )

    for index, role in enumerate(payload.get("work_experience") or []):
        parsed.work_experience.append(
            WorkExperienceIn(
                company=role["company"],
                title=role["title"],
                location=role.get("location"),
                start_date=_to_date(role.get("start_date")),
                end_date=_to_date(role.get("end_date")),
                is_current=bool(role.get("is_current")),
                highlights=role.get("highlights") or [],
                display_order=index,
            )
        )

    for index, school in enumerate(payload.get("education") or []):
        parsed.education.append(
            EducationIn(
                institution=school["institution"],
                degree=school.get("degree"),
                field_of_study=school.get("field_of_study"),
                start_date=_to_date(school.get("start_date")),
                end_date=_to_date(school.get("end_date")),
                grade=school.get("grade"),
                display_order=index,
            )
        )

    for skill in payload.get("skills") or []:
        parsed.skills.append(
            SkillIn(name=skill["name"], category=skill.get("category"))
        )

    return parsed


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")
LINK_PATTERNS = {
    "linkedin": re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+", re.I),
    "github": re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I),
}


def _parse_heuristically(raw_text: str) -> ParsedResume:
    """Regex-only extraction used when no Anthropic key is configured.

    Deliberately shallow: it pulls contact details and a skills line, and leaves
    work history to the user. Guessing at employment structure without a model
    produces confident-looking garbage, which is worse than an empty section.
    """
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    email_match = EMAIL_RE.search(raw_text)
    phone_match = PHONE_RE.search(raw_text)

    links = {}
    for name, pattern in LINK_PATTERNS.items():
        match = pattern.search(raw_text)
        if match:
            links[name] = match.group(0)

    # The name is almost always the first non-empty line and rarely contains
    # contact punctuation.
    full_name = None
    if lines and "@" not in lines[0] and len(lines[0]) < 60:
        full_name = lines[0]

    skills = [SkillIn(name=name) for name in _find_skills(lines)]

    return ParsedResume(
        full_name=full_name,
        email=email_match.group(0) if email_match else None,
        phone=phone_match.group(0) if phone_match else None,
        links=links,
        skills=skills,
        extraction_method="heuristic",
        confidence=0.3,
    )


# A standalone section heading: short, no sentence punctuation, and either all
# caps or title case. Used to stop the skills scan at the next section.
SECTION_HEADER_RE = re.compile(r"^[A-Z][A-Za-z /&]{1,30}:?$")


def _find_skills(lines: list[str]) -> list[str]:
    for index, line in enumerate(lines):
        # "Skills: Python, Go" — everything after the colon is the block.
        inline = re.match(r"(technical\s+|core\s+)?skills\s*:\s*(?P<rest>.+)", line, flags=re.I)
        if inline:
            return _split_skills(inline.group("rest"))

        # "SKILLS" / "Technical Skills:" on its own line — the block follows,
        # and ends at the next section heading.
        if re.fullmatch(r"(technical\s+|core\s+)?skills:?", line, flags=re.I):
            block: list[str] = []
            for candidate in lines[index + 1 : index + 6]:
                if SECTION_HEADER_RE.fullmatch(candidate):
                    break
                block.append(candidate)
            return _split_skills(" ".join(block))
    return []


def _split_skills(text: str) -> list[str]:
    parts = re.split(r"[,;|•·]", text)
    return [p.strip() for p in parts if 1 < len(p.strip()) <= 40][:50]


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
