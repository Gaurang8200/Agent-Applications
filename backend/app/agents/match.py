"""Match stage: score a job posting against the candidate's real profile.

Discover ranks by raw skill-overlap count, which treats "mentions Docker once"
the same as "is the core of the role". This stage replaces that with a judged
score: Claude reads the posting against the profile and returns a 0-100 fit
score, the reasoning behind it, and the gap between what the role wants and
what the candidate actually has.

The scorer judges; it never invents. Its skill lists are intersected against
the profile and the posting text downstream, so a hallucinated skill cannot
inflate a match.
"""

import json
from dataclasses import dataclass

import anthropic

from app.core.config import get_settings
from app.models import JobPosting, Profile

settings = get_settings()

SYSTEM_PROMPT = """You assess how well a candidate fits a specific job posting.

You are given the candidate's real profile and the posting. Judge the fit \
honestly. Do not assume experience the profile does not show, and do not credit \
the candidate for a requirement they clearly do not meet.

Scoring guide:
- 85-100: strong fit. Core requirements are directly evidenced in the profile.
- 65-84: good fit. Most core requirements met, gaps are learnable or adjacent.
- 40-64: partial fit. Some real overlap, but important requirements are missing.
- 0-39: weak fit. Overlap is incidental or the role targets a different track.

Weigh the requirements the posting emphasises most. A single keyword match in a \
long unrelated posting is a weak fit, not a strong one. Seniority mismatch, a \
different specialisation, and missing must-have technologies all pull the score \
down.

Write the reasoning for the candidate to read: two or three sentences, concrete, \
naming the specific evidence that drove the score."""

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "description": "Fit score from 0 to 100.",
        },
        "reasoning": {
            "type": "string",
            "description": "Two or three sentences explaining the score, naming "
            "specific evidence from the profile and the posting.",
        },
        "matched_skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Skills the candidate genuinely has that this role "
            "asks for. Only skills present in the candidate's profile.",
        },
        "missing_skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Requirements the posting asks for that the profile "
            "does not evidence.",
        },
    },
    "required": ["score", "reasoning", "matched_skills", "missing_skills"],
    "additionalProperties": False,
}


@dataclass
class MatchScore:
    score: float
    reasoning: str
    matched_skills: list[str]
    missing_skills: list[str]


def _profile_summary(profile: Profile) -> str:
    lines = [
        f"Headline: {profile.headline or '(none)'}",
        f"Summary: {profile.summary or '(none)'}",
        f"Location: {profile.location or '(none)'}",
        f"Skills: {', '.join(s.name for s in profile.skills) or '(none)'}",
        "",
        "Experience:",
    ]
    for exp in sorted(profile.work_experience, key=lambda w: w.display_order):
        end = "Present" if exp.is_current else (exp.end_date or "?")
        lines.append(f"- {exp.title} at {exp.company} ({exp.start_date or '?'} to {end})")
        for highlight in exp.highlights[:4]:
            lines.append(f"    {highlight}")
    for edu in sorted(profile.education, key=lambda e: e.display_order):
        lines.append(f"- Education: {edu.degree or ''} {edu.field_of_study or ''} at {edu.institution}")
    return "\n".join(lines)


def _posting_summary(posting: JobPosting) -> str:
    parts = [
        f"Title: {posting.title}",
        f"Company: {posting.company}",
        f"Location: {posting.location or 'not stated'}"
        f"{' (remote)' if posting.is_remote else ''}",
        "",
        "Description:",
        # Long postings add cost without changing the judgement much; the
        # requirements are near the top in practice.
        (posting.description or "")[:6000],
    ]
    return "\n".join(parts)


def score_match(profile: Profile, posting: JobPosting) -> MatchScore:
    """Score one posting against the profile. Requires an Anthropic API key."""
    if not settings.llm_enabled:
        raise RuntimeError(
            "Match scoring needs ANTHROPIC_API_KEY. Set it in .env and restart the API."
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        output_config={
            # Scoring is a judgement call on a bounded input; medium effort keeps
            # per-posting cost sane across a large queue.
            "effort": "medium",
            "format": {"type": "json_schema", "schema": SCORE_SCHEMA},
        },
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"CANDIDATE PROFILE:\n{_profile_summary(profile)}\n\n"
                    f"JOB POSTING:\n{_posting_summary(posting)}\n\n"
                    "Score the fit."
                ),
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Match scoring was declined by the safety system.")

    payload = json.loads(next(b.text for b in response.content if b.type == "text"))
    real_skills = {s.name.lower(): s.name for s in profile.skills}

    # Keep only skills the candidate actually lists, so a hallucinated match
    # cannot inflate the result the user sees.
    matched = []
    for skill in payload.get("matched_skills", []):
        actual = real_skills.get(skill.strip().lower())
        if actual and actual not in matched:
            matched.append(actual)

    return MatchScore(
        score=float(max(0, min(100, payload["score"]))),
        reasoning=payload["reasoning"],
        matched_skills=matched,
        missing_skills=payload.get("missing_skills", []),
    )
