"""Use-case tests: no Flask, no database. A fake unit of work stands in for PostgreSQL."""

import datetime

from flightlog.application.ingest import ingest_event
from flightlog.application.jobs import JobKind
from flightlog.contracts.ingest import IngestEvent, IngestOutcome
from tests.application.fakes import FakeUnitOfWork

COMMAND = IngestEvent(
    source="github",
    delivery_id="delivery-001",
    type="pull_request",
    occurred_at=datetime.datetime(2026, 11, 15, 10, 0, tzinfo=datetime.UTC),
    payload={"action": "opened"},
)


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


def test_a_new_event_is_queued_for_the_worker():
    uow = FakeUnitOfWork()

    result = ingest_event(COMMAND, uow)

    assert uow.jobs.enqueued == [(result.event_id, JobKind.APPLY_TO_SESSION)]


def test_a_duplicate_is_not_queued_again():
    uow = FakeUnitOfWork()
    ingest_event(COMMAND, uow)

    ingest_event(COMMAND, uow)

    assert len(uow.jobs.enqueued) == 1
