from typing import Protocol

from flightlog.application.jobs import Job, JobKind
from flightlog.domain import RecordedEvent


class EventStore(Protocol):
    def add_if_new(self, event: RecordedEvent) -> int | None:
        """Store the event unless (source, delivery_id) exists. Returns the new id, or None."""
        ...


class JobQueue(Protocol):
    def enqueue(self, event_id: int, kind: JobKind) -> None:
        """Add a job for the event. Part of the caller's transaction (ADR-0008)."""
        ...

    def claim_next(self) -> Job | None:
        """Lock the next due job for this transaction, skipping jobs other workers hold."""
        ...


class UnitOfWork(Protocol):
    """One transaction. Everything a use case changes is committed together, or not at all."""

    events: EventStore
    jobs: JobQueue

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class DatabaseProbe(Protocol):
    def __call__(self) -> bool:
        """True when the database answers."""
        ...
