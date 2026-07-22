"""Deterministic enforcement of the tailoring formatting rules.

The model is prompted to follow these rules, but prompts are not guarantees.
Everything here is checked in code so a violation is caught even when the model
slips, and fed back for one self-correction pass.
"""

import re

from app.schemas.tailor import (
    RuleViolation,
    TailoredAnschreiben,
    TailoredCV,
    TailoringConstraints,
)

# A hyphen with spaces on both sides — used as a connector/dash rather than
# inside a compound word. Reads as AI punctuation; flagged, not intra-word.
_CONNECTOR_HYPHEN = re.compile(r"\s-\s")
_WORD = re.compile(r"\b[\w'’]+\b", re.UNICODE)


def target_bullet_count(index: int, constraints: TailoringConstraints) -> int:
    counts = constraints.bullets_per_experience
    if not counts:
        return 0
    return counts[index] if index < len(counts) else counts[-1]


def _scan_text(text: str, constraints: TailoringConstraints, location: str) -> list[RuleViolation]:
    violations: list[RuleViolation] = []
    for ch in constraints.banned_chars:
        if ch in text:
            violations.append(
                RuleViolation(
                    location=location,
                    rule="banned_char",
                    detail=f"Contains disallowed character {ch!r}",
                )
            )
    if _CONNECTOR_HYPHEN.search(text):
        violations.append(
            RuleViolation(
                location=location,
                rule="connector_hyphen",
                detail="Uses ' - ' as a connector; rephrase without the dash",
            )
        )
    return violations


def validate_cv(cv: TailoredCV, constraints: TailoringConstraints) -> list[RuleViolation]:
    violations: list[RuleViolation] = []

    for exp_index, exp in enumerate(cv.experiences):
        loc = f"experience[{exp_index}]"
        expected = target_bullet_count(exp_index, constraints)
        if len(exp.bullets) != expected:
            violations.append(
                RuleViolation(
                    location=loc,
                    rule="bullet_count",
                    detail=f"Expected {expected} bullets, got {len(exp.bullets)}",
                )
            )

        for b_index, bullet in enumerate(exp.bullets):
            bloc = f"{loc}.bullet[{b_index}]"
            length = len(bullet)
            if length < constraints.bullet_min_chars:
                violations.append(
                    RuleViolation(
                        location=bloc,
                        rule="bullet_too_short",
                        detail=f"{length} chars, below {constraints.bullet_min_chars} "
                        "(under ~1.5 lines)",
                    )
                )
            elif length > constraints.bullet_max_chars:
                violations.append(
                    RuleViolation(
                        location=bloc,
                        rule="bullet_too_long",
                        detail=f"{length} chars, above {constraints.bullet_max_chars} "
                        "(over ~2 lines)",
                    )
                )
            violations.extend(_scan_text(bullet, constraints, bloc))

    return violations


def validate_anschreiben(
    anschreiben: TailoredAnschreiben,
    constraints: TailoringConstraints,
    sample_word_count: int | None,
) -> list[RuleViolation]:
    violations = _scan_text(anschreiben.body, constraints, "anschreiben")

    words = len(_WORD.findall(anschreiben.body))
    if sample_word_count:
        # Never longer than the sample; within tolerance below it.
        ceiling = sample_word_count
        floor = int(sample_word_count * (1 - constraints.anschreiben_word_tolerance))
        if words > ceiling:
            violations.append(
                RuleViolation(
                    location="anschreiben",
                    rule="too_long",
                    detail=f"{words} words exceeds the sample's {sample_word_count}",
                )
            )
        elif words < floor:
            violations.append(
                RuleViolation(
                    location="anschreiben",
                    rule="too_short",
                    detail=f"{words} words is more than "
                    f"{int(constraints.anschreiben_word_tolerance * 100)}% under "
                    f"the sample's {sample_word_count}",
                )
            )
    return violations


def word_count(text: str) -> int:
    return len(_WORD.findall(text))
