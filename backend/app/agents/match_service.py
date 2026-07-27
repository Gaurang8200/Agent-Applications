"""Batch scoring: walk a profile's unscored matches and record real fit scores."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.match import score_match
from app.models import Match, Profile


@dataclass
class ScoringSummary:
    scored: int
    skipped: int
    failed: int
    remaining: int


def unscored_matches(db: Session, profile: Profile, limit: int) -> list[Match]:
    return list(
        db.scalars(
            select(Match)
            .where(Match.profile_id == profile.id, Match.llm_score.is_(None))
            # Highest keyword overlap first, so a truncated batch still scores
            # the most promising postings.
            .order_by(Match.final_score.desc(), Match.created_at.desc())
            .limit(limit)
        )
    )


def count_unscored(db: Session, profile: Profile) -> int:
    return len(
        list(
            db.scalars(
                select(Match.id).where(
                    Match.profile_id == profile.id, Match.llm_score.is_(None)
                )
            )
        )
    )


def score_pending(
    db: Session,
    profile: Profile,
    *,
    limit: int = 10,
    rescore: bool = False,
) -> ScoringSummary:
    """Score up to `limit` of the profile's matches.

    Already-scored matches are skipped unless `rescore` is set, so repeated
    calls cost nothing and converge on a fully scored queue. A failure on one
    posting does not abort the batch.
    """
    if rescore:
        candidates = list(
            db.scalars(
                select(Match)
                .where(Match.profile_id == profile.id)
                .order_by(Match.created_at.desc())
                .limit(limit)
            )
        )
    else:
        candidates = unscored_matches(db, profile, limit)

    scored = skipped = failed = 0
    for match in candidates:
        if match.llm_score is not None and not rescore:
            skipped += 1
            continue
        try:
            result = score_match(profile, match.job_posting)
        except Exception:  # noqa: BLE001 - one bad posting must not stop the batch
            failed += 1
            continue

        match.llm_score = result.score
        match.final_score = result.score
        match.reasoning = result.reasoning
        match.matched_skills = result.matched_skills
        match.missing_skills = result.missing_skills
        scored += 1

    db.commit()
    return ScoringSummary(
        scored=scored,
        skipped=skipped,
        failed=failed,
        remaining=count_unscored(db, profile),
    )
