import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_profile
from app.db.session import get_db
from app.models import Application, JobPosting, Match, Profile
from app.schemas.tracker import (
    ApplicationDetail,
    ApplicationOut,
    BoardResponse,
    CreateApplicationRequest,
    TransitionRequest,
)
from app.services import tracker

router = APIRouter(prefix="/tracker", tags=["tracker"])


def _owned_application(db: Session, profile: Profile, application_id: uuid.UUID) -> Application:
    application = db.scalar(
        select(Application).where(
            Application.id == application_id, Application.profile_id == profile.id
        )
    )
    if application is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Application not found")
    return application


@router.post("/applications", response_model=ApplicationOut, status_code=http_status.HTTP_201_CREATED)
def create_application(
    payload: CreateApplicationRequest,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> Application:
    """Start tracking an application, from a match or a posting directly.

    Idempotent: tracking the same posting twice returns the existing record.
    """
    if payload.match_id:
        match = db.scalar(
            select(Match).where(
                Match.id == payload.match_id, Match.profile_id == profile.id
            )
        )
        if match is None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Match not found")
        return tracker.create_from_match(db, profile, match)

    if payload.job_posting_id:
        posting = db.scalar(
            select(JobPosting).where(JobPosting.id == payload.job_posting_id)
        )
        if posting is None:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Job posting not found")
        return tracker.create_application(db, profile, posting)

    raise HTTPException(
        http_status.HTTP_400_BAD_REQUEST, "Provide a match_id or a job_posting_id"
    )


@router.get("/board", response_model=BoardResponse)
def board(
    profile: Profile = Depends(get_current_profile), db: Session = Depends(get_db)
) -> BoardResponse:
    return BoardResponse(
        counts=tracker.board_counts(db, profile),
        applications=tracker.list_applications(db, profile),
    )


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Application]:
    return tracker.list_applications(db, profile, status=status_filter, limit=limit)


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
def get_application(
    application_id: uuid.UUID,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> Application:
    return _owned_application(db, profile, application_id)


@router.post("/applications/{application_id}/transition", response_model=ApplicationDetail)
def transition_application(
    application_id: uuid.UUID,
    payload: TransitionRequest,
    profile: Profile = Depends(get_current_profile),
    db: Session = Depends(get_db),
) -> Application:
    """Move an application to a new status.

    This endpoint is the user acting, so it may cross the approval gate into
    `submitted`. Agent-driven transitions go through the service directly and
    stop at `ready_for_review`.
    """
    application = _owned_application(db, profile, application_id)
    try:
        result = tracker.transition(
            db,
            application,
            to_status=payload.status,
            actor="user",
            message=payload.message,
        )
    except tracker.TransitionError as exc:
        raise HTTPException(http_status.HTTP_409_CONFLICT, str(exc)) from exc
    return result.application
