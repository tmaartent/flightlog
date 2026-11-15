from flightlog.application.ports import UnitOfWork
from flightlog.contracts.ingest import IngestEvent, IngestOutcome, IngestResult
from flightlog.domain import RecordedEvent


def ingest_event(command: IngestEvent, uow: UnitOfWork) -> IngestResult:
    """Record a delivered event exactly once, then commit (store before acknowledging: ADR-0003)."""
    event = RecordedEvent(
        source=command.source,
        delivery_id=command.delivery_id,
        type=command.type,
        occurred_at=command.occurred_at,
        payload=command.payload,
    )
    event_id = uow.events.add_if_new(event)
    uow.commit()

    if event_id is None:
        return IngestResult(IngestOutcome.DUPLICATE, None)
    return IngestResult(IngestOutcome.CREATED, event_id)
