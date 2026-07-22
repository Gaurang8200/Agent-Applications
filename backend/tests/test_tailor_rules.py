"""Tests for the deterministic tailoring rules and the truthful-assembly guard.

None of these need an API key — they exercise the code that runs after (or
instead of) the model call.
"""

from datetime import date

from app.agents import tailor
from app.agents.tailor_rules import (
    target_bullet_count,
    validate_anschreiben,
    validate_cv,
    word_count,
)
from app.schemas.tailor import (
    TailoredAnschreiben,
    TailoredCV,
    TailoredExperience,
    TailoringConstraints,
)

CONSTRAINTS = TailoringConstraints()
# A bullet comfortably inside the 140-210 char band, no banned punctuation.
GOOD_BULLET = (
    "Rebuilt the billing pipeline into an event driven service that cut invoice "
    "latency from several hours down to a few minutes for finance teams"
)


def _cv(bullet_counts: list[int], bullet: str = GOOD_BULLET) -> TailoredCV:
    experiences = [
        TailoredExperience(
            company=f"Co{i}", title="Engineer", bullets=[bullet] * n
        )
        for i, n in enumerate(bullet_counts)
    ]
    return TailoredCV(headline="X", summary="Y", skills=["Python"], experiences=experiences)


def test_target_bullet_count_uses_last_value_beyond_list():
    assert target_bullet_count(0, CONSTRAINTS) == 6
    assert target_bullet_count(1, CONSTRAINTS) == 4
    assert target_bullet_count(2, CONSTRAINTS) == 3
    # A fourth experience keeps the last configured count.
    assert target_bullet_count(3, CONSTRAINTS) == 3


def test_compliant_cv_has_no_violations():
    cv = _cv([6, 4, 3])
    assert validate_cv(cv, CONSTRAINTS) == []


def test_wrong_bullet_counts_flagged():
    cv = _cv([5, 4, 3])  # first should be 6
    violations = validate_cv(cv, CONSTRAINTS)
    assert any(v.rule == "bullet_count" and v.location == "experience[0]" for v in violations)


def test_banned_characters_flagged():
    for ch in ["—", "–", ":", ";"]:
        bad = GOOD_BULLET[:-1] + ch  # keep length in band, swap final char
        cv = _cv([6, 4, 3], bullet=bad)
        violations = validate_cv(cv, CONSTRAINTS)
        assert any(v.rule == "banned_char" for v in violations), ch


def test_connector_hyphen_flagged_but_intraword_allowed():
    connector = (
        "Owned the full backend service and delivered features fast "
        "- shipping weekly to production for the whole platform team here"
    )
    assert any(
        v.rule == "connector_hyphen"
        for v in validate_cv(_cv([6, 4, 3], connector), CONSTRAINTS)
    )
    intraword = (
        "Owned the full-stack service end to end and shipped user-facing features "
        "on a weekly cadence for the entire platform organization here"
    )
    assert not any(
        v.rule == "connector_hyphen"
        for v in validate_cv(_cv([6, 4, 3], intraword), CONSTRAINTS)
    )


def test_bullet_length_band():
    short = "Too short a bullet"
    long = "word " * 60
    assert any(
        v.rule == "bullet_too_short"
        for v in validate_cv(_cv([6, 4, 3], short), CONSTRAINTS)
    )
    assert any(
        v.rule == "bullet_too_long"
        for v in validate_cv(_cv([6, 4, 3], long), CONSTRAINTS)
    )


def test_anschreiben_length_band():
    sample_words = 100
    over = TailoredAnschreiben(body="wort " * 120, word_count=120)
    under = TailoredAnschreiben(body="wort " * 80, word_count=80)
    ok = TailoredAnschreiben(body="wort " * 98, word_count=98)

    assert any(
        v.rule == "too_long" for v in validate_anschreiben(over, CONSTRAINTS, sample_words)
    )
    assert any(
        v.rule == "too_short" for v in validate_anschreiben(under, CONSTRAINTS, sample_words)
    )
    assert validate_anschreiben(ok, CONSTRAINTS, sample_words) == []


def test_word_count():
    assert word_count("hallo welt drei") == 3
    assert word_count("") == 0


# --- Truthful-assembly guard ---------------------------------------------


class _FakeSkill:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeExperience:
    def __init__(self, company, title, order, current=False):
        self.company = company
        self.title = title
        self.location = "Berlin"
        self.start_date = date(2022, 1, 1)
        self.end_date = None if current else date(2023, 1, 1)
        self.is_current = current
        self.highlights = ["did real work"]
        self.display_order = order


class _FakeProfile:
    def __init__(self):
        self.headline = "Real Headline"
        self.summary = "Real summary"
        self.skills = [_FakeSkill("Python"), _FakeSkill("Go")]
        self.work_experience = [
            _FakeExperience("AcmeCo", "Senior Engineer", 0, current=True),
            _FakeExperience("DataForge", "Engineer", 1),
        ]


def test_assemble_keeps_real_identity_and_drops_invented_skills():
    profile = _FakeProfile()
    # The model tries to add a skill the candidate never had and to rename the
    # employer. Neither should survive assembly.
    payload = {
        "headline": "Tailored Headline",
        "summary": "Tailored summary",
        "skills": ["Go", "Python", "Rust", "Kubernetes"],  # Rust/K8s are invented
        "experiences": [
            {"index": 0, "bullets": ["b1", "b2"]},
            {"index": 1, "bullets": ["b3"]},
        ],
        "anschreiben": "Sehr geehrte Damen und Herren",
    }
    cv, anschreiben = tailor._assemble(payload, profile, CONSTRAINTS)

    # Invented skills dropped; only real ones kept, in the model's order.
    assert cv.skills == ["Go", "Python"]
    # Employer identity comes from the profile, not the model.
    assert cv.experiences[0].company == "AcmeCo"
    assert cv.experiences[0].title == "Senior Engineer"
    assert cv.experiences[0].is_current is True
    assert cv.experiences[0].start_date == "2022-01-01"
    # Model-supplied bullet text is applied by index.
    assert cv.experiences[0].bullets == ["b1", "b2"]
    assert cv.experiences[1].bullets == ["b3"]
    assert anschreiben.word_count == word_count(anschreiben.body)
