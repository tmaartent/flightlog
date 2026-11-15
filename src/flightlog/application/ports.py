from typing import Protocol

from flightlog.application.jobs import Job, JobKind
from flightlog.domain import AgentSession, RecordedEvent


class EventStore(Protocol):
    def add_if_new(self, event: RecordedEvent) -> int | None:
        """Store the event unless (source, delivery_id) exists. Returns the new id, or None."""
        ...

    def get(self, event_id: int) -> RecordedEvent | None:
        """The event with this id. Changes to it are saved when the unit of work commits."""
        ...


class SessionRepository(Protocol):
    def get(self, source: str, external_id: str) -> AgentSession | None:
        """The session with this id in its source. Changes are saved on commit."""
        ...

    def add(self, session: AgentSession) -> None:
        """Store a new session. Assigns session.id straight away, so events can refer to it."""
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
    sessions: SessionRepository

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class DatabaseProbe(Protocol):
    def __call__(self) -> bool:
        """True when the database answers."""
        ...
