from flightlog.application.ports import UnitOfWork
from flightlog.domain import RecordedEvent


def unprocessed_event(event_id: int, uow: UnitOfWork) -> RecordedEvent | None:
    """The event a job is for, or None when an earlier attempt already applied and committed it.

    Raises LookupError for an unknown event, so the job fails and is retried.
    """
    event = uow.events.get(event_id)
    if event is None:
        raise LookupError(f"event {event_id} does not exist")
    if event.processed_at is not None:
        return None
    return event
