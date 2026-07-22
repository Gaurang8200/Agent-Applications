"""The Tailor stage: rewrite the candidate's real experience to align with a
specific job description.

Truthfulness is enforced structurally, not just requested:
- Company, title, location, and dates are copied from the real profile after
  the model returns. The model only supplies rewritten bullet text, so it
  cannot alter employment identity.
- Returned skills are intersected with the candidate's real skills; anything
  the model adds that the candidate never listed is dropped.

Formatting rules are enforced by app.agents.tailor_rules with one
self-correction pass.
"""

import json

import anthropic

from app.agents import tailor_rules
from app.core.config import get_settings
from app.models import Profile
from app.schemas.tailor import (
    TailoredAnschreiben,
    TailoredCV,
    TailoredExperience,
    TailoringConstraints,
    TailorResult,
)

settings = get_settings()

SYSTEM_PROMPT = """You tailor a candidate's existing CV and German cover letter \
(Anschreiben) to a specific job.

HARD TRUTH RULE — this overrides every other instruction:
- Work only from the REAL experience the candidate gives you. You may reword, \
reorder, sharpen, and quantify what is genuinely there, and you may foreground \
transferable work that is real. You must NOT invent employers, job titles, \
dates, tools, certifications, metrics, or accomplishments the candidate never \
had. If the job wants something the candidate lacks, speak to the closest real, \
adjacent experience honestly — never fake the missing skill.

Rewrite goals:
- Mirror the job description's language and priorities using the candidate's \
real background.
- Lead each bullet with the strongest match to the role.
- Keep the CV to one page and do not change its structure. You only rewrite \
bullet text, choose which real skills to list, and write the summary/headline.

Bullet formatting:
- Produce EXACTLY the requested number of bullets per experience.
- Each bullet must read as a complete thought spanning roughly one and a half \
to two lines. Not one line, not three.
- Write like a person, not a machine. Do not use the characters colon, \
semicolon, em dash, or en dash anywhere. Do not use a hyphen surrounded by \
spaces as a connector. Intra-word hyphens like full-stack are fine.
- No leading dashes or bullet symbols in the text itself.

Anschreiben:
- Do not restate CV bullets. Explain the impact the candidate brought to teams \
and what they would bring to this company.
- The candidate's skills are already on the CV, so do not narrate "I \
implemented X" mechanically, but do make the relevant strengths clear. Balance \
the two.
- Match the sample's structure and stay at or just under its length. Same \
punctuation rules as the bullets."""


def _build_schema(profile: Profile, constraints: TailoringConstraints) -> dict:
    return {
        "type": "object",
        "properties": {
            "headline": {"type": "string"},
            "summary": {"type": "string"},
            "skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only skills the candidate already has, reordered "
                "to foreground the job's priorities.",
            },
            "experiences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Index of the real experience this "
                            "rewrite corresponds to.",
                        },
                        "bullets": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["index", "bullets"],
                    "additionalProperties": False,
                },
            },
            "anschreiben": {"type": "string"},
        },
        "required": ["headline", "summary", "skills", "experiences", "anschreiben"],
        "additionalProperties": False,
    }


def _profile_context(profile: Profile, constraints: TailoringConstraints) -> str:
    lines = ["CANDIDATE PROFILE (the only source of truth):", ""]
    lines.append(f"Headline: {profile.headline or '(none)'}")
    lines.append(f"Summary: {profile.summary or '(none)'}")
    real_skills = [s.name for s in profile.skills]
    lines.append(f"Real skills (choose only from these): {', '.join(real_skills) or '(none)'}")
    lines.append("")
    lines.append("Experiences (most recent first). Rewrite bullets per the count rule:")

    ordered = sorted(profile.work_experience, key=lambda w: w.display_order)
    for index, exp in enumerate(ordered):
        want = tailor_rules.target_bullet_count(index, constraints)
        span = f"{exp.start_date or '?'} to {'Present' if exp.is_current else (exp.end_date or '?')}"
        lines.append(
            f"\n[index {index}] {exp.title} at {exp.company} ({span}) "
            f"-> write {want} bullets"
        )
        for highlight in exp.highlights:
            lines.append(f"  real: {highlight}")
    return "\n".join(lines)


def _job_context(job_title: str | None, company: str | None, jd: str) -> str:
    header = "TARGET JOB:"
    if job_title:
        header += f"\nTitle: {job_title}"
    if company:
        header += f"\nCompany: {company}"
    return f"{header}\n\nDescription:\n{jd}"


def _call_model(
    client: anthropic.Anthropic,
    schema: dict,
    profile_ctx: str,
    job_ctx: str,
    constraints: TailoringConstraints,
    sample_anschreiben: str | None,
    correction: str | None,
) -> dict:
    user = [profile_ctx, "", job_ctx, ""]
    counts = ", ".join(str(c) for c in constraints.bullets_per_experience)
    user.append(
        f"Bullet counts by experience order: {counts} (later experiences use the "
        "last number). Each bullet {min}-{max} characters.".format(
            min=constraints.bullet_min_chars, max=constraints.bullet_max_chars
        )
    )
    if sample_anschreiben:
        user.append(
            f"\nSAMPLE ANSCHREIBEN (match its structure and length, in its "
            f"language):\n{sample_anschreiben}"
        )
    if correction:
        user.append(
            "\nYour previous attempt broke these rules. Fix every one and return "
            f"the full result again:\n{correction}"
        )

    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": schema},
        },
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(user)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Tailoring was declined by the safety system.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _assemble(
    payload: dict, profile: Profile, constraints: TailoringConstraints
) -> tuple[TailoredCV, TailoredAnschreiben]:
    """Reconstruct the tailored CV using REAL identity fields and REAL skills.

    The model supplies only bullet text and ordering choices; identity and the
    skill whitelist come from the profile, so nothing can be fabricated here.
    """
    ordered = sorted(profile.work_experience, key=lambda w: w.display_order)
    bullets_by_index = {
        item["index"]: item["bullets"] for item in payload.get("experiences", [])
    }

    experiences: list[TailoredExperience] = []
    for index, exp in enumerate(ordered):
        experiences.append(
            TailoredExperience(
                company=exp.company,
                title=exp.title,
                location=exp.location,
                start_date=exp.start_date.isoformat() if exp.start_date else None,
                end_date=exp.end_date.isoformat() if exp.end_date else None,
                is_current=exp.is_current,
                bullets=bullets_by_index.get(index, []),
            )
        )

    real_skill_lookup = {s.name.lower(): s.name for s in profile.skills}
    kept_skills: list[str] = []
    for skill in payload.get("skills", []):
        match = real_skill_lookup.get(skill.strip().lower())
        if match and match not in kept_skills:
            kept_skills.append(match)

    cv = TailoredCV(
        headline=payload.get("headline") or profile.headline,
        summary=payload.get("summary") or profile.summary,
        skills=kept_skills,
        experiences=experiences,
    )
    body = payload.get("anschreiben", "")
    anschreiben = TailoredAnschreiben(body=body, word_count=tailor_rules.word_count(body))
    return cv, anschreiben


def tailor(
    profile: Profile,
    job_description: str,
    *,
    job_title: str | None = None,
    company: str | None = None,
    constraints: TailoringConstraints | None = None,
    sample_anschreiben: str | None = None,
    max_passes: int = 2,
) -> TailorResult:
    if not settings.llm_enabled:
        raise RuntimeError(
            "Tailoring needs ANTHROPIC_API_KEY. Set it in .env and restart the API."
        )
    if not profile.work_experience:
        raise ValueError(
            "Profile has no work experience to tailor. Upload and apply a resume first."
        )

    constraints = constraints or TailoringConstraints()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    schema = _build_schema(profile, constraints)
    profile_ctx = _profile_context(profile, constraints)
    job_ctx = _job_context(job_title, company, job_description)
    sample_words = (
        tailor_rules.word_count(sample_anschreiben) if sample_anschreiben else None
    )

    correction: str | None = None
    cv = anschreiben = None
    violations = []
    for _ in range(max_passes):
        payload = _call_model(
            client, schema, profile_ctx, job_ctx, constraints, sample_anschreiben, correction
        )
        cv, anschreiben = _assemble(payload, profile, constraints)
        violations = validate(cv, anschreiben, constraints, sample_words)
        if not violations:
            break
        correction = "\n".join(f"- {v.location}: {v.detail}" for v in violations)

    return TailorResult(
        cv=cv,
        anschreiben=anschreiben,
        violations=violations,
        compliant=not violations,
        extraction_method="llm",
    )


def validate(cv, anschreiben, constraints, sample_words):
    return [
        *tailor_rules.validate_cv(cv, constraints),
        *tailor_rules.validate_anschreiben(anschreiben, constraints, sample_words),
    ]
