"""Use-case tests for applying events to sessions, on the fake unit of work."""

import datetime

import pytest

from flightlog.application.apply_to_session import apply_to_session, repo_name
from flightlog.application.jobs import JobKind
from flightlog.contracts.ingest import CLAUDE
from flightlog.domain import AgentSessionStatus, RecordedEvent
from tests.application.fakes import FakeUnitOfWork

T0 = datetime.datetime(2026, 11, 15, 10, 0, tzinfo=datetime.UTC)
NOW = T0 + datetime.timedelta(hours=1)


def record(
    uow: FakeUnitOfWork, type_: str, at: datetime.datetime, branch: str | None = None, **hook
) -> int:
    """Store a Claude hook event as ingest would. Returns its id."""
    hook = {"session_id": "s-1", "cwd": "/home/dev/flightlog", **hook}
    event = RecordedEvent(
        source=CLAUDE,
        delivery_id=f"{type_}-{at.isoformat()}",
        type=type_,
        occurred_at=at,
        payload={"hook": hook, "git": {"branch": branch}},
    )
    return uow.events.add_if_new(event)


def test_the_first_event_creates_the_session():
    uow = FakeUnitOfWork()
    event_id = record(uow, "SessionStart", T0)

    apply_to_session(event_id, NOW, uow)

    session = uow.agent_sessions.get(CLAUDE, "s-1")
    assert session is not None
    assert session.repo == "flightlog"
    assert session.started_at == T0
    assert session.status is AgentSessionStatus.ACTIVE
    event = uow.events.get(event_id)
    assert event.agent_session_id == session.id
    assert event.processed_at == NOW


def test_later_events_update_the_same_session():
    uow = FakeUnitOfWork()
    start = record(uow, "SessionStart", T0)
    end = record(uow, "SessionEnd", T0 + datetime.timedelta(minutes=5))

    apply_to_session(start, NOW, uow)
    apply_to_session(end, NOW, uow)

    assert len(uow.agent_sessions.sessions) == 1
    session = uow.agent_sessions.get(CLAUDE, "s-1")
    assert session.ended_at == T0 + datetime.timedelta(minutes=5)
    assert session.status is AgentSessionStatus.STOPPED


def test_events_in_the_wrong_order_give_the_same_session():
    uow = FakeUnitOfWork()
    tool = record(uow, "PostToolUse", T0 + datetime.timedelta(minutes=1))
    end = record(uow, "SessionEnd", T0 + datetime.timedelta(minutes=5))
    start = record(uow, "SessionStart", T0)

    for event_id in (end, tool, start):
        apply_to_session(event_id, NOW, uow)

    session = uow.agent_sessions.get(CLAUDE, "s-1")
    assert session.started_at == T0
    assert session.ended_at == T0 + datetime.timedelta(minutes=5)
    assert session.status is AgentSessionStatus.STOPPED


def test_applying_an_event_twice_changes_nothing():
    uow = FakeUnitOfWork()
    event_id = record(uow, "SessionStart", T0)
    apply_to_session(event_id, NOW, uow)

    apply_to_session(event_id, NOW + datetime.timedelta(minutes=1), uow)

    assert uow.events.get(event_id).processed_at == NOW


def test_the_branch_of_the_latest_event_is_kept():
    uow = FakeUnitOfWork()
    later = record(uow, "PostToolUse", T0 + datetime.timedelta(minutes=1), branch="feat/x")
    start = record(uow, "SessionStart", T0, branch="main")

    apply_to_session(later, NOW, uow)
    apply_to_session(start, NOW, uow)

    assert uow.agent_sessions.get(CLAUDE, "s-1").branch == "feat/x"


def test_an_event_from_before_m3_has_no_branch():
    uow = FakeUnitOfWork()
    event = RecordedEvent(
        source=CLAUDE,
        delivery_id="old",
        type="SessionStart",
        occurred_at=T0,
        payload={"hook": {"session_id": "s-1", "cwd": "/home/dev/flightlog"}},  # no "git"
    )

    apply_to_session(uow.events.add_if_new(event), NOW, uow)

    assert uow.agent_sessions.get(CLAUDE, "s-1").branch is None


def test_an_event_without_a_session_id_is_marked_processed():
    uow = FakeUnitOfWork()
    event_id = record(uow, "SessionStart", T0, session_id=None)

    apply_to_session(event_id, NOW, uow)

    assert uow.agent_sessions.sessions == {}
    assert uow.events.get(event_id).processed_at == NOW


def test_an_unknown_event_fails_so_the_job_is_retried():
    with pytest.raises(LookupError):
        apply_to_session(999, NOW, FakeUnitOfWork())


def test_the_use_case_leaves_the_commit_to_the_worker():
    uow = FakeUnitOfWork()

    apply_to_session(record(uow, "SessionStart", T0), NOW, uow)

    assert uow.commits == 0


@pytest.mark.parametrize(
    ("cwd", "expected"),
    [
        ("/home/dev/flightlog", "flightlog"),
        (r"C:\Users\dev\Workspace\flightlog", "flightlog"),
        ("/home/dev/flightlog/", "flightlog"),
        ("", ""),
    ],
)
def test_repo_name_is_the_last_folder(cwd, expected):
    assert repo_name(cwd) == expected


# --- the summary job (M5, ADR-0018) ---------------------------------------------------------


def summarize_jobs(uow: FakeUnitOfWork) -> list[int]:
    return [j.event_id for j in uow.jobs.enqueued if j.kind is JobKind.SUMMARIZE_SESSION]


def test_session_end_queues_its_summary():
    uow = FakeUnitOfWork()
    start = record(uow, "SessionStart", T0)
    end = record(uow, "SessionEnd", T0 + datetime.timedelta(minutes=5))

    apply_to_session(start, NOW, uow)
    assert summarize_jobs(uow) == []
    apply_to_session(end, NOW, uow)

    assert summarize_jobs(uow) == [end]


def test_a_late_event_for_a_stopped_session_queues_the_summary_again():
    uow = FakeUnitOfWork()
    end = record(uow, "SessionEnd", T0 + datetime.timedelta(minutes=5))
    late = record(uow, "PostToolUse", T0 + datetime.timedelta(minutes=1), tool_name="Edit")

    apply_to_session(end, NOW, uow)
    apply_to_session(late, NOW, uow)

    assert summarize_jobs(uow) == [end, late]


def test_applying_an_event_twice_queues_its_summary_once():
    uow = FakeUnitOfWork()
    end = record(uow, "SessionEnd", T0)

    apply_to_session(end, NOW, uow)
    apply_to_session(end, NOW, uow)  # at least once: the second run finds it processed

    assert summarize_jobs(uow) == [end]
