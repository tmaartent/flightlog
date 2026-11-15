from sqlalchemy.orm import Session

from flightlog.infrastructure.db import get_session
from flightlog.infrastructure.event_store import SqlEventStore
from flightlog.infrastructure.job_queue import SqlJobQueue


class SqlUnitOfWork:
    """UnitOfWork on one SQLAlchemy session: the request's session, from db.get_session()."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.events = SqlEventStore(session)
        self.jobs = SqlJobQueue(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


def request_unit_of_work() -> SqlUnitOfWork:
    """A unit of work on the current request's session (closed in teardown, see db.py)."""
    return SqlUnitOfWork(get_session())
