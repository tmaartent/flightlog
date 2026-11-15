from flightlog.application.jobs import JobKind
from flightlog.application.ports import UnitOfWork
from flightlog.contracts.ingest import IngestEvent, IngestOutcome, IngestResult
from flightlog.domain import RecordedEvent


def ingest_event(command: IngestEvent, uow: UnitOfWork) -> IngestResult:
    """Record a delivered event exactly once and queue it for the worker, in one transaction.

    Event and job are committed together: there is no moment where an event exists without
    its job, so no event is ever lost between ingest and processing (ADR-0008).
    """
    event = RecordedEvent(
        source=command.source,
        delivery_id=command.delivery_id,
        type=command.type,
        occurred_at=command.occurred_at,
        payload=command.payload,
    )
    event_id = uow.events.add_if_new(event)
    if event_id is not None:
        uow.jobs.enqueue(event_id, JobKind.APPLY_TO_SESSION)
    uow.commit()

    if event_id is None:
        return IngestResult(IngestOutcome.DUPLICATE, None)
    return IngestResult(IngestOutcome.CREATED, event_id)
