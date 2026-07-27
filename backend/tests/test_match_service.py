"""Tests for batch match scoring — no API key needed, the scorer is stubbed."""

import pytest

from app.agents import match_service
from app.agents.match import MatchScore


class _FakeSkill:
    def __init__(self, name):
        self.name = name


class _FakePosting:
    def __init__(self, title="Backend Engineer"):
        self.title = title
        self.company = "Acme"
        self.location = "Berlin"
        self.is_remote = False
        self.description = "Python, FastAPI"


class _FakeMatch:
    def __init__(self, final_score=1.0, llm_score=None):
        self.id = id(self)
        self.final_score = final_score
        self.llm_score = llm_score
        self.reasoning = None
        self.matched_skills = []
        self.missing_skills = []
        self.job_posting = _FakePosting()


class _FakeProfile:
    id = "p1"
    skills = [_FakeSkill("Python")]


class _FakeSession:
    """Stands in for a Session; the query paths are patched out per test."""

    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


@pytest.fixture
def patched(monkeypatch):
    def _apply(candidates, scorer=None, remaining=0):
        monkeypatch.setattr(
            match_service, "unscored_matches", lambda db, p, limit: candidates[:limit]
        )
        monkeypatch.setattr(match_service, "count_unscored", lambda db, p: remaining)
        monkeypatch.setattr(
            match_service,
            "score_match",
            scorer
            or (
                lambda profile, posting: MatchScore(
                    score=82.0,
                    reasoning="Strong Python overlap.",
                    matched_skills=["Python"],
                    missing_skills=["Kafka"],
                )
            ),
        )

    return _apply


def test_scores_write_through_to_the_match(patched):
    match = _FakeMatch()
    patched([match])
    summary = match_service.score_pending(_FakeSession(), _FakeProfile(), limit=5)

    assert summary.scored == 1
    assert match.llm_score == 82.0
    # final_score is replaced by the judged score, not the keyword placeholder.
    assert match.final_score == 82.0
    assert match.reasoning == "Strong Python overlap."
    assert match.matched_skills == ["Python"]
    assert match.missing_skills == ["Kafka"]


def test_already_scored_matches_are_skipped(patched):
    scored = _FakeMatch(llm_score=70.0)
    patched([scored])
    summary = match_service.score_pending(_FakeSession(), _FakeProfile(), limit=5)

    assert summary.scored == 0
    assert summary.skipped == 1
    assert scored.llm_score == 70.0  # untouched


def test_one_failure_does_not_abort_the_batch(patched):
    good, bad = _FakeMatch(), _FakeMatch()
    calls = {"n": 0}

    def flaky(profile, posting):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("upstream hiccup")
        return MatchScore(80.0, "ok", ["Python"], [])

    patched([bad, good], scorer=flaky)
    summary = match_service.score_pending(_FakeSession(), _FakeProfile(), limit=5)

    assert summary.failed == 1
    assert summary.scored == 1
    assert good.llm_score == 80.0


def test_limit_caps_the_batch(patched):
    matches = [_FakeMatch() for _ in range(10)]
    patched(matches, remaining=7)
    summary = match_service.score_pending(_FakeSession(), _FakeProfile(), limit=3)

    assert summary.scored == 3
    assert summary.remaining == 7
    assert all(m.llm_score is None for m in matches[3:])


def test_session_is_committed(patched):
    session = _FakeSession()
    patched([_FakeMatch()])
    match_service.score_pending(session, _FakeProfile(), limit=1)
    assert session.committed
