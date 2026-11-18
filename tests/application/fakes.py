"""In-memory stand-ins for the ports, so use cases can be tested without a database."""

import datetime
from types import TracebackType
from typing import Self

from flightlog.application.jobs import Job, JobKind
from flightlog.domain import AgentSession, PullRequest, RecordedEvent


class FakeEventLog:
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
        self.enqueued: list[Job] = []
        self.latest_error: str | None = None
        self.delay: datetime.timedelta | None = None
        self.given_up: bool = False

    def enqueue(self, event_id: int, kind: JobKind, attempts: int = 0) -> None:
        self.enqueued.append(Job(len(self.enqueued) + 1, event_id, kind, attempts))

    def claim_next(self) -> Job | None:
        if len(self.enqueued) == 0:
            return None
        return self.enqueued[0]

    def retry_later(self, job: Job, error: str, delay: datetime.timedelta) -> None:
        self.latest_error = error
        self.delay = delay

    def give_up(self, job: Job, error: str) -> None:
        self.latest_error = error
        self.given_up = True

    def complete(self, job: Job) -> None:
        self.enqueued.remove(job)


class FakeAgentSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str], AgentSession] = {}

    def get(self, source: str, external_id: str) -> AgentSession | None:
        return self.sessions.get((source, external_id))

    def add(self, session: AgentSession) -> None:
        session.id = len(self.sessions) + 1
        self.sessions[(session.source, session.external_id)] = session


class FakePullRequestRepository:
    def __init__(self) -> None:
        self.pull_requests: dict[tuple[str, int], PullRequest] = {}

    def get(self, repo: str, number: int) -> PullRequest | None:
        return self.pull_requests.get((repo, number))

    def add(self, pull_request: PullRequest) -> None:
        pull_request.id = len(self.pull_requests) + 1
        self.pull_requests[(pull_request.repo, pull_request.number)] = pull_request


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.events = FakeEventLog()
        self.jobs = FakeJobQueue()
        self.agent_sessions = FakeAgentSessionRepository()
        self.pull_requests = FakePullRequestRepository()
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass
