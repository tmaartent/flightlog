import datetime

import pytest

from flightlog.application.digest import RULES_VERSION, rebuild_digests, summarize_session
from flightlog.application.jobs import JobKind
from flightlog.contracts.digest import DigestEvent
from flightlog.contracts.ingest import CLAUDE
from flightlog.domain import RecordedEvent
from tests.application.fakes import FakeUnitOfWork

T0 = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)
NOW = T0 + datetime.timedelta(hours=1)


def stored_event(uow, session_id: int | None = 1) -> int:
    event = RecordedEvent(CLAUDE, f"d-{len(uow.events.events)}", "SessionEnd", T0, {"hook": {}})
    event.agent_session_id = session_id
    return uow.events.add_if_new(event)


def edit(n: int, path: str) -> DigestEvent:
    return DigestEvent(n, "PostToolUse", T0, "Edit", f"/w/shop/{path}", None, "/w/shop")


def test_the_job_stores_the_digest_of_the_events_session():
    uow = FakeUnitOfWork()
    uow.digests.sessions[1] = (T0, T0 + datetime.timedelta(minutes=10))
    uow.digests.events[1] = [edit(1, "a.py"), edit(2, "b.py")]

    summarize_session(stored_event(uow), NOW, uow)

    stored = uow.digests.saved[1]
    assert stored.files_touched == ["a.py", "b.py"]
    assert stored.duration_seconds == 600
    assert uow.commits == 0  # the worker commits, with the job's removal


def test_an_event_without_a_session_has_nothing_to_summarize():
    uow = FakeUnitOfWork()

    summarize_session(stored_event(uow, session_id=None), NOW, uow)

    assert uow.digests.saved == {}


def test_an_unknown_event_or_session_fails_so_the_job_is_retried():
    uow = FakeUnitOfWork()
    with pytest.raises(LookupError):
        summarize_session(999, NOW, uow)
    with pytest.raises(LookupError):
        summarize_session(stored_event(uow, session_id=42), NOW, uow)


def test_rebuild_queues_a_job_per_stale_session_and_commits():
    uow = FakeUnitOfWork()
    uow.digests.stale = [11, 12]

    assert rebuild_digests(uow) == 2
    assert [(j.event_id, j.kind) for j in uow.jobs.enqueued] == [
        (11, JobKind.SUMMARIZE_SESSION),
        (12, JobKind.SUMMARIZE_SESSION),
    ]
    assert uow.digests.stale_asked == [RULES_VERSION]
    assert uow.commits == 1


def test_rebuild_skips_a_session_whose_job_is_already_queued():
    uow = FakeUnitOfWork()
    uow.jobs.enqueue(11, JobKind.SUMMARIZE_SESSION)
    uow.digests.stale = [11]

    assert rebuild_digests(uow) == 0
    assert len(uow.jobs.enqueued) == 1
