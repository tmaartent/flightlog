"""Use-case tests: no Flask, no database. A fake unit of work stands in for PostgreSQL."""

import dataclasses
import datetime

from flightlog.application.ingest import ingest_event
from flightlog.application.jobs import JobKind
from flightlog.contracts.ingest import CLAUDE, GITHUB, IngestEvent, IngestOutcome
from tests.application.fakes import FakeUnitOfWork

GITHUB_COMMAND = IngestEvent(
    source=GITHUB,
    delivery_id="delivery-001",
    type="pull_request",
    occurred_at=datetime.datetime(2026, 11, 15, 10, 0, tzinfo=datetime.UTC),
    payload={"action": "opened"},
)

CLAUDE_COMMAND = IngestEvent(
    source=CLAUDE,
    delivery_id="delivery-002",
    type="PostToolUse",
    occurred_at=datetime.datetime(2026, 11, 15, 10, 0, tzinfo=datetime.UTC),
    payload={"hook": {"session_id": "s-1"}},
)


def test_a_new_event_is_recorded_and_committed():
    uow = FakeUnitOfWork()

    result = ingest_event(GITHUB_COMMAND, uow)

    assert result.outcome is IngestOutcome.CREATED
    assert result.event_id == 1
    (event,) = uow.events.events.values()
    assert (event.source, event.delivery_id, event.type) == (
        GITHUB,
        "delivery-001",
        "pull_request",
    )
    assert event.occurred_at == GITHUB_COMMAND.occurred_at
    assert event.payload == {"action": "opened"}
    assert uow.commits == 1


def test_the_same_delivery_twice_is_a_duplicate():
    uow = FakeUnitOfWork()
    ingest_event(GITHUB_COMMAND, uow)

    result = ingest_event(GITHUB_COMMAND, uow)

    assert result.outcome is IngestOutcome.DUPLICATE
    assert result.event_id is None
    assert len(uow.events.events) == 1


def test_a_new_event_is_queued_for_the_worker():
    uow = FakeUnitOfWork()

    result = ingest_event(GITHUB_COMMAND, uow)
    result2 = ingest_event(CLAUDE_COMMAND, uow)

    (job, second_job) = uow.jobs.enqueued
    assert (job.event_id, job.kind) == (result.event_id, JobKind.APPLY_PULL_REQUEST)
    assert (second_job.event_id, second_job.kind) == (result2.event_id, JobKind.APPLY_TO_SESSION)


def test_a_duplicate_is_not_queued_again():
    uow = FakeUnitOfWork()
    ingest_event(GITHUB_COMMAND, uow)

    ingest_event(GITHUB_COMMAND, uow)

    assert len(uow.jobs.enqueued) == 1


def test_an_event_without_work_is_recorded_but_not_queued():
    uow = FakeUnitOfWork()
    push = dataclasses.replace(GITHUB_COMMAND, type="push")

    result = ingest_event(push, uow)

    assert result.outcome is IngestOutcome.CREATED
    assert uow.jobs.enqueued == []
