from types import TracebackType
from typing import Self

from flask import current_app
from sqlalchemy.orm import Session

from flightlog.infrastructure.agent_session_repository import SqlAgentSessionRepository
from flightlog.infrastructure.connector_repository import SqlConnectorRepository
from flightlog.infrastructure.db import get_session
from flightlog.infrastructure.digest_repository import SqlDigestRepository
from flightlog.infrastructure.event_log import SqlEventLog
from flightlog.infrastructure.job_queue import SqlJobQueue
from flightlog.infrastructure.pull_request_repository import SqlPullRequestRepository


class SqlUnitOfWork:
    """UnitOfWork on one SQLAlchemy session. As a context manager, it closes the session."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.events = SqlEventLog(session)
        self.jobs = SqlJobQueue(session)
        self.agent_sessions = SqlAgentSessionRepository(session)
        self.pull_requests = SqlPullRequestRepository(session)
        self.connectors = SqlConnectorRepository(session)
        self.digests = SqlDigestRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rollback()
        self._session.close()


def request_unit_of_work() -> SqlUnitOfWork:
    """A unit of work on the current request's session (closed in teardown, see db.py)."""
    return SqlUnitOfWork(get_session())


def new_unit_of_work() -> SqlUnitOfWork:
    """A unit of work on a fresh session, closed when its `with` block ends.

    For the worker: a CLI command has one app context for its whole run, so the session on
    flask.g would be shared by every job. Each job gets its own session instead.
    """
    return SqlUnitOfWork(current_app.extensions["sessionmaker"]())
