from typing import Protocol

from flightlog.domain import RecordedEvent


class EventStore(Protocol):
    def add_if_new(self, event: RecordedEvent) -> int | None:
        """Store the event unless (source, delivery_id) exists. Returns the new id, or None."""
        ...


class UnitOfWork(Protocol):
    """One transaction. Everything a use case changes is committed together, or not at all."""

    events: EventStore

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class DatabaseProbe(Protocol):
    def __call__(self) -> bool:
        """True when the database answers."""
        ...
