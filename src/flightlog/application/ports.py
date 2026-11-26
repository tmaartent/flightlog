import datetime
from types import TracebackType
from typing import Protocol, Self

from flightlog.application.jobs import Job, JobKind
from flightlog.contracts.admin import FailedJob
from flightlog.contracts.audit import AuditEntry, AuditFilter, AuditPage
from flightlog.contracts.connectors import ConnectorInfo
from flightlog.contracts.sessions import (
    LinkedPullRequest,
    SessionFilter,
    SessionPage,
    SessionSummary,
)
from flightlog.contracts.timeline import SessionEvent
from flightlog.domain import AgentSession, Connector, PullRequest, RecordedEvent


class EventLog(Protocol):
    def add_if_new(self, event: RecordedEvent) -> int | None:
        """Store the event unless (source, delivery_id) exists. Returns the new id, or None."""
        ...

    def get(self, event_id: int) -> RecordedEvent | None:
        """The event with this id. Changes to it are saved when the unit of work commits."""
        ...


class AgentSessionRepository(Protocol):
    def get(self, source: str, external_id: str) -> AgentSession | None:
        """The session with this id in its source. Changes are saved on commit."""
        ...

    def add(self, session: AgentSession) -> None:
        """Store a new session. Assigns session.id straight away, so events can refer to it."""
        ...


class PullRequestRepository(Protocol):
    def get(self, repo: str, number: int) -> PullRequest | None:
        """The pull request with this number in the repo. Changes are saved on commit."""
        ...

    def add(self, pull_request: PullRequest) -> None:
        """Store a new pull request."""
        ...


class ConnectorRepository(Protocol):
    def get(self, connector_id: int) -> Connector | None:
        """The connector with this id, revoked or not. Changes are saved on commit."""
        ...

    def get_by_prefix(self, key_prefix: str) -> Connector | None:
        """The connector whose key has this prefix, revoked or not."""
        ...

    def get_by_name(self, name: str) -> Connector | None:
        """The connector with this name, revoked or not. Changes are saved on commit."""
        ...

    def add(self, connector: Connector) -> None:
        """Store a new connector."""
        ...


class JobQueue(Protocol):
    def enqueue(self, event_id: int, kind: JobKind) -> None:
        """Add a job for the event. Part of the caller's transaction (ADR-0008)."""
        ...

    def claim_next(self) -> Job | None:
        """Lock the next due job for this transaction, skipping jobs other workers hold."""
        ...

    def complete(self, job: Job) -> None:
        """Delete the job: its work is done and committed with it (ADR-0008)."""
        ...

    def retry_later(self, job: Job, error: str, delay: datetime.timedelta) -> None:
        """Count the attempt and make the job due again after `delay`, on the database clock."""
        ...

    def give_up(self, job: Job, error: str) -> None:
        """Count the attempt and mark the job failed; it stays visible for a manual retry."""
        ...

    def retry_now(self, job_id: int) -> bool:
        """Make a failed job due now with zero attempts. False if no failed job has this id."""
        ...


class UnitOfWork(Protocol):
    """One transaction. Everything a use case changes is committed together, or not at all."""

    events: EventLog
    jobs: JobQueue
    agent_sessions: AgentSessionRepository
    pull_requests: PullRequestRepository
    connectors: ConnectorRepository

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


class AgentSessionQueries(Protocol):
    """Read side: views for the dashboard and the API. No aggregates, nothing to commit."""

    def linked_pull_requests(self, session_id: int) -> list[LinkedPullRequest]:
        """The PRs opened from the session's branch in its repo, oldest first (ADR-0009)."""
        ...

    def list_sessions(self, session_filter: SessionFilter) -> SessionPage:
        """Sessions matching the filter, newest first, one page after `session_filter.after`."""
        ...

    def repos(self) -> list[str]:
        """Every repo that has a session, sorted: the choices for the repo filter."""
        ...

    def session_summary(self, session_id: int) -> SessionSummary | None:
        """One session as a list row, or None if there is no session with this id."""
        ...

    def session_events(self, session_id: int) -> list[SessionEvent]:
        """The session's applied events, ordered by occurred_at, then id (ADR-0010)."""
        ...


class JobQueries(Protocol):
    """Read side of the queue, for the admin page."""

    def failed_jobs(self) -> list[FailedJob]:
        """Jobs the worker gave up on, most recently failed first."""
        ...


class ConnectorQueries(Protocol):
    """Read side of the connectors, for the admin page and `flask connector list`."""

    def list_connectors(self) -> list[ConnectorInfo]:
        """Every connector, revoked ones too, oldest first."""
        ...


class AuditLog(Protocol):
    """Append-only: there is no update and no delete (ADR-0015)."""

    def record(self, entry: AuditEntry) -> None:
        """Write the entry in its own transaction, apart from the request's unit of work."""
        ...


class AuditQueries(Protocol):
    def list_entries(self, audit_filter: AuditFilter) -> AuditPage:
        """Rows matching the filter, newest first, one page before `audit_filter.before`."""
        ...


class DatabaseProbe(Protocol):
    def __call__(self) -> bool:
        """True when the database answers."""
        ...
