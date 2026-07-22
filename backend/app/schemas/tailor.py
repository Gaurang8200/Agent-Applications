"""Schemas for the tailoring stage.

The agent rewrites the candidate's real experience to align with a specific job
description. It never invents employers, titles, dates, tools, or metrics the
candidate did not have — it re-emphasizes and re-frames what is already true.

Formatting rules (from the product spec) are enforced downstream by
`app.agents.tailor_rules`, not trusted to the model alone.
"""

from pydantic import BaseModel, Field


class TailoringConstraints(BaseModel):
    """Tunable formatting rules for the tailored CV and cover letter.

    Defaults encode the spec: 6/4/3 bullets for the first three experiences,
    each bullet roughly 1.5–2 rendered lines, one page, no AI-tell punctuation.
    """

    # Bullet counts per experience, most-recent first. Experiences beyond this
    # list keep the last value (see tailor_rules.target_bullet_count).
    bullets_per_experience: list[int] = Field(default_factory=lambda: [6, 4, 3])

    # A rendered CV line is ~95 chars at typical margins/font. 1.5–2 lines is
    # the acceptance band; these are character proxies, checked per bullet.
    bullet_min_chars: int = 140
    bullet_max_chars: int = 210

    # Characters that read as machine-written and are disallowed in bullets and
    # in the cover letter body. Intra-word hyphens (full-stack) are allowed; a
    # hyphen used as a connector (" - ") is flagged separately.
    banned_chars: list[str] = Field(default_factory=lambda: ["—", "–", ":", ";"])

    max_cv_pages: int = 1

    # Anschreiben length is measured against the user's sample; +/- this
    # fraction is allowed, never more than the sample.
    anschreiben_word_tolerance: float = 0.05


class TailoredExperience(BaseModel):
    """One work experience with rewritten bullets. Identity fields are copied
    from the real profile and must not change."""

    company: str
    title: str
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    bullets: list[str] = Field(default_factory=list)


class TailoredCV(BaseModel):
    headline: str | None = None
    summary: str | None = None
    # Skills reordered/selected to foreground the JD's priorities — but only
    # skills the candidate actually listed.
    skills: list[str] = Field(default_factory=list)
    experiences: list[TailoredExperience] = Field(default_factory=list)


class TailoredAnschreiben(BaseModel):
    """German cover letter. Impact-focused prose, not a restatement of CV
    bullets. Same structure and roughly the same length as the user's sample."""

    body: str
    word_count: int = 0


class RuleViolation(BaseModel):
    location: str  # e.g. "experience[0].bullet[2]" or "anschreiben"
    rule: str
    detail: str


class TailorRequest(BaseModel):
    # Provide either a stored posting id or raw JD text.
    job_posting_id: str | None = None
    job_description: str | None = None
    job_title: str | None = None
    company: str | None = None
    constraints: TailoringConstraints = Field(default_factory=TailoringConstraints)


class TailorResult(BaseModel):
    cv: TailoredCV
    anschreiben: TailoredAnschreiben
    violations: list[RuleViolation] = Field(default_factory=list)
    # True when every hard rule passed after the self-correction loop.
    compliant: bool = True
    extraction_method: str = "llm"
