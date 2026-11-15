"""Use-case tests: no Flask, no database. A fake unit of work stands in for PostgreSQL."""

import datetime

from flightlog.application.ingest import ingest_event
from flightlog.contracts.ingest import IngestEvent, IngestOutcome
from flightlog.domain import RecordedEvent

COMMAND = IngestEvent(
    source="github",
    delivery_id="delivery-001",
    type="pull_request",
    occurred_at=datetime.datetime(2026, 11, 15, 10, 0, tzinfo=datetime.UTC),
    payload={"action": "opened"},
)


class FakeEventStore:
    def __init__(self) -> None:
        self.events: dict[tuple[str, str], RecordedEvent] = {}

    def add_if_new(self, event: RecordedEvent) -> int | None:
        key = (event.source, event.delivery_id)
        if key in self.events:
            return None
        event.id = len(self.events) + 1
        self.events[key] = event
        return event.id


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.events = FakeEventStore()
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


def test_a_new_event_is_recorded_and_committed():
    uow = FakeUnitOfWork()

    result = ingest_event(COMMAND, uow)

    assert result.outcome is IngestOutcome.CREATED
    assert result.event_id == 1
    (event,) = uow.events.events.values()
    assert (event.source, event.delivery_id, event.type) == (
        "github",
        "delivery-001",
        "pull_request",
    )
    assert event.occurred_at == COMMAND.occurred_at
    assert event.payload == {"action": "opened"}
    assert uow.commits == 1


def test_the_same_delivery_twice_is_a_duplicate():
    uow = FakeUnitOfWork()
    ingest_event(COMMAND, uow)

    result = ingest_event(COMMAND, uow)

    assert result.outcome is IngestOutcome.DUPLICATE
    assert result.event_id is None
    assert len(uow.events.events) == 1
