import datetime

import pytest

from flightlog.contracts.ingest import CLAUDE
from flightlog.domain import AgentSession, AgentSessionStatus
from flightlog.domain.agent_session import SESSION_END


def test_record_rejects_naive_datetime():
    session = AgentSession(CLAUDE, "Foo", "/", datetime.datetime.now(datetime.UTC))

    with pytest.raises(ValueError):
        session.record("SessionStart", datetime.datetime.now())


def test_any_event_moves_started_at_if_older():
    session = AgentSession(CLAUDE, "Foo", "/", datetime.datetime.now(datetime.UTC))
    earlier = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
    even_earlier = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=2)

    session.record("SessionStart", earlier)

    assert session.started_at == earlier

    session.record(SESSION_END, even_earlier)

    assert session.started_at == even_earlier

    # Newer events do not move started_at

    session.record("PostToolUse", earlier)

    assert session.started_at == even_earlier


def test_only_session_end_moves_ended_at_if_newer():
    session = AgentSession(CLAUDE, "Foo", "/", datetime.datetime.now(datetime.UTC))
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
    even_later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=2)

    session.record(SESSION_END, later)
    assert session.ended_at == later

    session.record(SESSION_END, even_later)
    assert session.ended_at == even_later

    # Older events do not move ended_at

    session.record(SESSION_END, later)
    assert session.ended_at == even_later


def test_status_only_moves_forward():
    session = AgentSession(CLAUDE, "Foo", "/", datetime.datetime.now(datetime.UTC))
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
    even_later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=2)

    assert session.status == AgentSessionStatus.ACTIVE

    session.record(SESSION_END, later)
    assert session.status == AgentSessionStatus.STOPPED

    session.record("PostToolUse", even_later)  # a late event does not reopen it
    assert session.ended_at == later  # and only SessionEnd moves the end
    assert session.status == AgentSessionStatus.STOPPED


def test_recording_the_same_twice_changes_nothing():
    now = datetime.datetime.now(datetime.UTC)
    session = AgentSession(CLAUDE, "Foo", "/", now)
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)

    session.record(SESSION_END, later)
    assert session.started_at == now
    assert session.ended_at == later
    assert session.status == AgentSessionStatus.STOPPED

    session.record(SESSION_END, later)

    assert session.started_at == now
    assert session.ended_at == later
    assert session.status == AgentSessionStatus.STOPPED


def test_branch_is_recorded_when_present_only_by_newer():
    now = datetime.datetime.now(datetime.UTC)
    session = AgentSession(CLAUDE, "Foo", "/", now)
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)

    session.record(SESSION_END, later, branch="branch")
    assert session.branch_seen_at == later
    assert session.branch == "branch"

    session.record(SESSION_END, now, branch="other_branch")
    assert session.branch_seen_at == later
    assert session.branch == "branch"


def test_an_event_without_a_branch_keeps_the_branch():
    now = datetime.datetime.now(datetime.UTC)
    session = AgentSession(CLAUDE, "Foo", "/", now)
    session.record("SessionStart", now, branch="main")

    session.record("PostToolUse", now + datetime.timedelta(minutes=1), branch=None)

    assert session.branch == "main"
    assert session.branch_seen_at == now
