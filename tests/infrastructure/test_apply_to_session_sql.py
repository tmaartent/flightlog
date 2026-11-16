"""The use case on the real adapters: the new session is inserted and the event links to it."""

import datetime

import pytest

from flightlog.application.apply_to_session import apply_to_session
from flightlog.domain import AgentSessionStatus, RecordedEvent
from flightlog.infrastructure.unit_of_work import SqlUnitOfWork

T0 = datetime.datetime(2026, 11, 15, 10, 0, tzinfo=datetime.UTC)


def store(uow: SqlUnitOfWork, type_: str, at: datetime.datetime) -> int:
    event = RecordedEvent(
        source="claude",
        delivery_id=type_,
        type=type_,
        occurred_at=at,
        payload={"hook": {"session_id": "s-1", "cwd": r"C:\work\flightlog"}},
    )
    return uow.events.add_if_new(event)


@pytest.mark.db
def test_a_session_is_created_and_updated_in_the_database(db_session):
    uow = SqlUnitOfWork(db_session)
    start = store(uow, "SessionStart", T0)
    end = store(uow, "SessionEnd", T0 + datetime.timedelta(minutes=5))

    apply_to_session(start, T0, uow)
    apply_to_session(end, T0, uow)
    uow.commit()
    db_session.expunge_all()  # read back from the database, not from the identity map

    session = uow.sessions.get("claude", "s-1")
    assert session is not None
    assert session.repo == "flightlog"
    assert session.started_at == T0
    assert session.ended_at == T0 + datetime.timedelta(minutes=5)
    assert session.status is AgentSessionStatus.STOPPED
    assert uow.events.get(start).agent_session_id == session.id
    assert uow.events.get(end).processed_at == T0
