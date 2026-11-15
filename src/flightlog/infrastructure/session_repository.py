from sqlalchemy import select
from sqlalchemy.orm import Session

from flightlog.domain import AgentSession


class SqlSessionRepository:
    """SessionRepository on PostgreSQL. Loaded sessions are tracked, so changes save on commit."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, source: str, external_id: str) -> AgentSession | None:
        statement = select(AgentSession).filter_by(source=source, external_id=external_id)
        return self._session.scalars(statement).one_or_none()

    def add(self, session: AgentSession) -> None:
        self._session.add(session)
        self._session.flush()  # INSERT now, so session.id is set for the event that refers to it
