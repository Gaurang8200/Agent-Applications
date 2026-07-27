"""Runs the autopilot cycle on an interval inside the API process.

A plain asyncio task rather than a job framework: there is one job, it is
idempotent, and its durable output is rows in the database. The cycle itself is
synchronous and blocking, so it runs in a worker thread to keep the event loop
free for requests.
"""

import asyncio
import logging

from app.core.config import get_settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)
settings = get_settings()

_task: asyncio.Task | None = None


def _run_cycle_blocking() -> None:
    from app.agents.autopilot import run_cycle

    db = SessionLocal()
    try:
        run_cycle(db)
    finally:
        db.close()


async def _loop() -> None:
    interval = max(5, settings.autopilot_interval_minutes) * 60
    logger.info("Autopilot enabled; cycle every %s minutes", interval // 60)
    while True:
        try:
            await asyncio.to_thread(_run_cycle_blocking)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed cycle must not kill the loop
            logger.exception("Autopilot cycle failed")
        await asyncio.sleep(interval)


def start() -> None:
    global _task
    if not settings.autopilot_enabled:
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="autopilot")


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _task = None


def is_running() -> bool:
    return _task is not None and not _task.done()
