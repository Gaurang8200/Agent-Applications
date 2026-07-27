from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import autopilot
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import SessionLocal, get_db
from app.models import User
from app.services import scheduler

settings = get_settings()
router = APIRouter(prefix="/autopilot", tags=["autopilot"])


class CycleReportOut(BaseModel):
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    profiles: int
    discovered: int
    scored: int
    prepared: int
    prepared_for: list[str]
    problems: list[str]


class StatusOut(BaseModel):
    enabled: bool
    running: bool
    interval_minutes: int
    min_score: float
    score_limit: int
    prepare_limit: int
    llm_enabled: bool
    recent_cycles: list[CycleReportOut] = Field(default_factory=list)


def _serialize(report: autopilot.CycleReport) -> CycleReportOut:
    return CycleReportOut(
        started_at=report.started_at.isoformat(),
        finished_at=report.finished_at.isoformat() if report.finished_at else None,
        duration_seconds=report.duration_seconds,
        profiles=report.profiles,
        discovered=report.discovered,
        scored=report.scored,
        prepared=report.prepared,
        prepared_for=report.prepared_for,
        problems=report.problems,
    )


@router.get("/status", response_model=StatusOut)
def status(user: User = Depends(get_current_user)) -> StatusOut:
    """Whether the loop is running, and what it did on recent cycles."""
    return StatusOut(
        enabled=settings.autopilot_enabled,
        running=scheduler.is_running(),
        interval_minutes=settings.autopilot_interval_minutes,
        min_score=settings.autopilot_min_score,
        score_limit=settings.autopilot_score_limit,
        prepare_limit=settings.autopilot_prepare_limit,
        llm_enabled=settings.llm_enabled,
        recent_cycles=[_serialize(r) for r in autopilot.history()],
    )


def _run_detached() -> None:
    db: Session = SessionLocal()
    try:
        autopilot.run_cycle(db)
    finally:
        db.close()


@router.post("/run", status_code=202)
def run_now(
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Trigger one cycle immediately.

    Returns straight away and runs in the background — a cycle fetches from
    several sources and calls the model repeatedly, which is far too slow to
    hold a request open. Poll `/autopilot/status` for the result.
    """
    background.add_task(_run_detached)
    return {"status": "started", "detail": "Poll /autopilot/status for the report."}
