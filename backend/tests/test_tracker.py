"""Tests for the application lifecycle and the approval gate.

The gate is the product's central safety rule: an agent prepares, a user
submits. These tests pin that behaviour so it cannot regress silently.
"""

import pytest

from app.models.application import AGENT_TERMINAL_STATUS
from app.services import tracker
from app.services.tracker import TransitionError


class _FakeApplication:
    def __init__(self, status="draft"):
        self.id = "app-1"
        self.status = status
        self.submitted_at = None
        self.approved_by_user_at = None
        self.tailored_resume = None
        self.cover_letter = None
        self.cv_local_path = None
        self.cover_letter_local_path = None
        self.tailored_resume_s3_key = None
        self.cover_letter_s3_key = None


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass

    @property
    def events(self):
        return [o for o in self.added if hasattr(o, "event_type")]


def _move(app, to_status, actor, db=None):
    return tracker.transition(db or _FakeSession(), app, to_status=to_status, actor=actor)


# --- the approval gate ---------------------------------------------------


def test_agent_may_prepare_up_to_the_gate():
    db = _FakeSession()
    app = _FakeApplication("draft")
    _move(app, "tailoring", "agent", db)
    _move(app, "prefilling", "agent", db)
    _move(app, AGENT_TERMINAL_STATUS, "agent", db)
    assert app.status == AGENT_TERMINAL_STATUS


def test_agent_cannot_submit():
    app = _FakeApplication("ready_for_review")
    with pytest.raises(TransitionError, match="agent cannot move"):
        _move(app, "submitted", "agent")
    assert app.status == "ready_for_review"
    assert app.submitted_at is None


def test_agent_cannot_reach_any_post_submission_status():
    for beyond in ("submitted", "acknowledged", "interviewing", "offer"):
        app = _FakeApplication("ready_for_review")
        with pytest.raises(TransitionError):
            _move(app, beyond, "agent")


def test_user_submission_stamps_the_approval():
    app = _FakeApplication("ready_for_review")
    db = _FakeSession()
    _move(app, "submitted", "user", db)

    assert app.status == "submitted"
    assert app.submitted_at is not None
    # The audit trail proving a human approved this specific application.
    assert app.approved_by_user_at is not None
    assert db.events[-1].actor == "user"
    assert db.events[-1].event_type == "status:submitted"


# --- lifecycle -----------------------------------------------------------


def test_illegal_jump_is_rejected():
    app = _FakeApplication("draft")
    with pytest.raises(TransitionError, match="Cannot move from"):
        _move(app, "submitted", "user")


def test_terminal_states_have_no_exit():
    for terminal in ("rejected", "withdrawn"):
        app = _FakeApplication(terminal)
        with pytest.raises(TransitionError, match="final state"):
            _move(app, "interviewing", "user")


def test_unknown_status_and_actor_rejected():
    app = _FakeApplication("draft")
    with pytest.raises(TransitionError, match="Unknown status"):
        _move(app, "banana", "user")
    with pytest.raises(TransitionError, match="Unknown actor"):
        _move(app, "tailoring", "robot")


def test_no_op_transition_rejected():
    app = _FakeApplication("draft")
    with pytest.raises(TransitionError, match="already"):
        _move(app, "draft", "user")


def test_withdraw_is_available_from_every_live_status():
    for live in ("draft", "tailoring", "prefilling", "ready_for_review", "submitted"):
        app = _FakeApplication(live)
        _move(app, "withdrawn", "user")
        assert app.status == "withdrawn"


def test_full_happy_path_records_every_actor():
    db = _FakeSession()
    app = _FakeApplication("draft")
    _move(app, "tailoring", "agent", db)
    _move(app, "ready_for_review", "agent", db)
    _move(app, "submitted", "user", db)
    _move(app, "interviewing", "user", db)

    actors = [e.actor for e in db.events]
    assert actors == ["agent", "agent", "user", "user"]
    assert app.status == "interviewing"


# --- events and documents ------------------------------------------------


def test_record_event_rejects_unknown_actor():
    with pytest.raises(ValueError, match="Unknown actor"):
        tracker.record_event(
            _FakeSession(), _FakeApplication(), event_type="note", actor="nobody"
        )


def test_attach_documents_writes_paths_and_an_event():
    db = _FakeSession()
    app = _FakeApplication("tailoring")
    tracker.attach_documents(
        db,
        app,
        cover_letter="Sehr geehrte Damen und Herren",
        cv_local_path="/tmp/Zalando/CV.pdf",
        cover_letter_local_path="/tmp/Zalando/Anschreiben.pdf",
    )
    assert app.cv_local_path == "/tmp/Zalando/CV.pdf"
    assert db.events[-1].event_type == "documents_attached"
    assert db.events[-1].actor == "agent"
