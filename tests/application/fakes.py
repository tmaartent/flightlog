"""In-memory stand-ins for the ports, so use cases can be tested without a database."""

import datetime
from types import TracebackType
from typing import Self

from flightlog.application.jobs import Job, JobKind
from flightlog.contracts.digest import DigestEvent, SessionDigest
from flightlog.contracts.sessions import LinkedPullRequest, SessionSummary
from flightlog.contracts.timeline import SessionEvent
from flightlog.domain import AgentSession, Connector, PullRequest, RecordedEvent


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
        self.failed: list[Job] = []
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

    def enqueue_unless_queued(self, event_id: int, kind: JobKind) -> bool:
        if any((j.event_id, j.kind) == (event_id, kind) for j in self.enqueued):
            return False
        self.enqueue(event_id, kind)
        return True

    def complete(self, job: Job) -> None:
        self.enqueued.remove(job)

    def retry_now(self, job_id: int) -> bool:
        job = next((j for j in self.failed if j.id == job_id), None)
        if job is None:
            return False
        self.failed.remove(job)
        self.enqueued.append(Job(job.id, job.event_id, job.kind, attempts=0))
        return True


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


class FakeConnectorRepository:
    def __init__(self) -> None:
        self.connectors: list[Connector] = []

    def get(self, connector_id: int) -> Connector | None:
        return next((c for c in self.connectors if c.id == connector_id), None)

    def get_by_prefix(self, key_prefix: str) -> Connector | None:
        return next((c for c in self.connectors if c.key_prefix == key_prefix), None)

    def get_by_name(self, name: str) -> Connector | None:
        return next((c for c in self.connectors if c.name == name), None)

    def add(self, connector: Connector) -> None:
        connector.id = len(self.connectors) + 1
        self.connectors.append(connector)


class FakeDigestRepository:
    def __init__(self) -> None:
        self.sessions: dict[int, tuple] = {}
        self.events: dict[int, list[DigestEvent]] = {}
        self.saved: dict[int, SessionDigest] = {}
        self.stale: list[int] = []
        self.stale_asked: list[int] = []

    def session(self, agent_session_id: int):
        return self.sessions.get(agent_session_id)

    def source_events(self, agent_session_id: int) -> list[DigestEvent]:
        return self.events.get(agent_session_id, [])

    def save(self, digest: SessionDigest) -> None:
        self.saved[digest.agent_session_id] = digest

    def stale_sessions(self, rules_version: int) -> list[int]:
        self.stale_asked.append(rules_version)
        return self.stale


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.events = FakeEventLog()
        self.jobs = FakeJobQueue()
        self.agent_sessions = FakeAgentSessionRepository()
        self.pull_requests = FakePullRequestRepository()
        self.connectors = FakeConnectorRepository()
        self.digests = FakeDigestRepository()
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


class FakeAgentSessionQueries:
    """The read side as dicts keyed on session id; what a test doesn't set is empty."""

    def __init__(self) -> None:
        self.summaries: dict[int, SessionSummary] = {}
        self.events: dict[int, list[SessionEvent]] = {}
        self.pull_requests: dict[int, list[LinkedPullRequest]] = {}

    def session_summary(self, session_id: int) -> SessionSummary | None:
        return self.summaries.get(session_id)

    def session_events(self, session_id: int) -> list[SessionEvent]:
        return self.events.get(session_id, [])

    def linked_pull_requests(self, session_id: int) -> list[LinkedPullRequest]:
        return self.pull_requests.get(session_id, [])
