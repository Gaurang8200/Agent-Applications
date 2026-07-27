"""Tests for the autonomous loop and the single-user allowlist."""

import pytest

from app.agents import autopilot
from app.core.config import Settings


# --- allowlist -----------------------------------------------------------


def _settings(allowed: str) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@localhost:5433/db",
        s3_access_key="k",
        s3_secret_key="s",
        jwt_secret="x" * 32,
        allowed_emails=allowed,
    )


def test_empty_allowlist_is_open():
    s = _settings("")
    assert s.email_allowed("anyone@example.com")


def test_allowlist_restricts_and_is_case_insensitive():
    s = _settings("Owner@Example.com")
    assert s.email_allowed("owner@example.com")
    assert s.email_allowed("OWNER@EXAMPLE.COM")
    assert not s.email_allowed("someone.else@example.com")


def test_allowlist_accepts_several_addresses():
    s = _settings("a@x.com, b@y.com")
    assert s.email_allowed("b@y.com")
    assert not s.email_allowed("c@z.com")


# --- candidate selection -------------------------------------------------


class _FakePosting:
    def __init__(self, company="Acme"):
        self.company = company
        self.title = "Backend Engineer"
        self.description = "Python"


class _FakeMatch:
    def __init__(self, job_posting_id, score, llm_score=80.0, status="new"):
        self.id = job_posting_id
        self.job_posting_id = job_posting_id
        self.final_score = score
        self.llm_score = llm_score
        self.status = status
        self.job_posting = _FakePosting()


class _FakeScalars:
    """Mimics Session.scalars for the two queries the selector issues."""

    def __init__(self, tracked, matches):
        self._tracked = tracked
        self._matches = matches
        self._calls = 0

    def __call__(self, _query):
        self._calls += 1
        return self._tracked if self._calls == 1 else self._matches


class _FakeSession:
    def __init__(self, tracked, matches):
        self.scalars = _FakeScalars(tracked, matches)


def test_already_tracked_matches_are_skipped(monkeypatch):
    # The selector builds SQLAlchemy queries; the fake session returns our rows
    # regardless of the query, so ordering/filtering by score is exercised in
    # the Python layer only.
    tracked = ["job-1"]
    matches = [_FakeMatch("job-1", 90.0), _FakeMatch("job-2", 85.0)]
    db = _FakeSession(tracked, matches)

    picked = autopilot._candidates_for_preparation(
        db, _FakeProfile(), min_score=60.0, limit=5
    )
    assert [m.job_posting_id for m in picked] == ["job-2"]


def test_prepare_limit_caps_selection():
    matches = [_FakeMatch(f"job-{i}", 90.0) for i in range(10)]
    db = _FakeSession([], matches)
    picked = autopilot._candidates_for_preparation(
        db, _FakeProfile(), min_score=60.0, limit=3
    )
    assert len(picked) == 3


class _FakeProfile:
    id = "p1"
    skills = ["Python"]


# --- history -------------------------------------------------------------


def test_history_is_newest_first_and_bounded():
    autopilot._history.clear()
    from datetime import UTC, datetime

    for i in range(autopilot._HISTORY_LIMIT + 5):
        autopilot._record(
            autopilot.CycleReport(started_at=datetime.now(UTC), discovered=i)
        )

    entries = autopilot.history()
    assert len(entries) == autopilot._HISTORY_LIMIT
    # Newest first.
    assert entries[0].discovered > entries[-1].discovered


def test_cycle_report_duration():
    from datetime import UTC, datetime, timedelta

    start = datetime.now(UTC)
    report = autopilot.CycleReport(started_at=start)
    assert report.duration_seconds is None
    report.finished_at = start + timedelta(seconds=42)
    assert report.duration_seconds == pytest.approx(42.0)


def test_prepare_stops_when_templates_are_missing(monkeypatch):
    """The loop must not present an empty application as ready for review."""
    from app.core import config

    monkeypatch.setattr(
        autopilot.settings, "cv_template_path", "/nonexistent/cv.docx", raising=False
    )
    monkeypatch.setattr(
        autopilot.settings,
        "anschreiben_template_path",
        "/nonexistent/letter.docx",
        raising=False,
    )
    report = autopilot.CycleReport(started_at=__import__("datetime").datetime.now(
        __import__("datetime").UTC
    ))
    ok = autopilot._prepare_one(
        db=None, profile=_FakeProfile(), match=_FakeMatch("job-1", 90.0), report=report
    )
    assert ok is False
    assert any("template missing" in p for p in report.problems)
    assert config  # keep the import meaningful for linters
