import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.discover.filters import JobFilterConfig
from app.agents.discover.service import discover_jobs
from app.api.deps import get_current_profile
from app.db.session import get_db
from app.models import Match, Profile
from app.schemas.job import DiscoverRequest, DiscoverResponse, MatchOut

router = APIRouter(tags=["jobs"])


def _config_from_request(payload: DiscoverRequest) -> JobFilterConfig:
    config = JobFilterConfig()
    if payload.role_keywords is not None:
        config.role_keywords = [k.lower() for k in payload.role_keywords]
    if payload.excluded_companies is not None:
        config.excluded_companies = [c.lower() for c in payload.excluded_companies]
    if payload.max_required_years is not None:
        config.max_required_years = payload.max_required_years
    if payload.posted_within_days is not None:
        config.posted_within_days = payload.posted_within_days
    return config


@router.post("/discover", response_model=DiscoverResponse)
def discover(
    payload: DiscoverRequest = DiscoverRequest(),
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> DiscoverResponse:
    """Pull recent postings from job boards and record skill matches.

    Needs at least one skill on the profile — with none, nothing can match.
    """
    if not profile.skills:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Add skills to your profile first (upload a resume). "
            "Discovery matches postings against your skills.",
        )

    try:
        summary = discover_jobs(
            db, profile, config=_config_from_request(payload), max_pages=payload.max_pages
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Job board request failed: {exc}",
        ) from exc

    return DiscoverResponse(**summary.__dict__)


@router.get("/jobs/matches", response_model=list[MatchOut])
def list_matches(
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Match]:
    query = (
        select(Match)
        .where(Match.profile_id == profile.id)
        .order_by(Match.final_score.desc(), Match.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        query = query.where(Match.status == status_filter)
    return list(db.scalars(query))
