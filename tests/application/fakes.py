"""In-memory stand-ins for the ports, so use cases can be tested without a database."""

from flightlog.application.jobs import JobKind
from flightlog.domain import AgentSession, RecordedEvent


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

    def get(self, event_id: int) -> RecordedEvent | None:
        return next((e for e in self.events.values() if e.id == event_id), None)


class FakeJobQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[int, JobKind]] = []

    def enqueue(self, event_id: int, kind: JobKind) -> None:
        self.enqueued.append((event_id, kind))

    def claim_next(self):
        raise NotImplementedError  # the use cases don't claim; the worker does


class FakeSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str], AgentSession] = {}

    def get(self, source: str, external_id: str) -> AgentSession | None:
        return self.sessions.get((source, external_id))

    def add(self, session: AgentSession) -> None:
        session.id = len(self.sessions) + 1
        self.sessions[(session.source, session.external_id)] = session


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.events = FakeEventStore()
        self.jobs = FakeJobQueue()
        self.sessions = FakeSessionRepository()
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass
