from sqlalchemy import select
from sqlalchemy.orm import Session

from flightlog.contracts.connectors import ConnectorInfo
from flightlog.domain import Connector
from flightlog.infrastructure.db import get_session
from flightlog.infrastructure.tables import connectors


class SqlConnectorRepository:
    """ConnectorRepository on PostgreSQL. Loaded connectors are tracked: revokes save on commit."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_prefix(self, key_prefix: str) -> Connector | None:
        statement = select(Connector).filter_by(key_prefix=key_prefix)
        return self._session.scalars(statement).one_or_none()

    def get_by_name(self, name: str) -> Connector | None:
        statement = select(Connector).filter_by(name=name)
        return self._session.scalars(statement).one_or_none()

    def add(self, connector: Connector) -> None:
        self._session.add(connector)


class SqlConnectorQueries:
    """ConnectorQueries on PostgreSQL: the columns that are safe to show, never the hash."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_connectors(self) -> list[ConnectorInfo]:
        c = connectors
        statement = select(c.c.name, c.c.key_prefix, c.c.created_at, c.c.revoked_at).order_by(
            c.c.created_at, c.c.id
        )
        return [
            ConnectorInfo(
                name=row.name,
                prefix=row.key_prefix,
                created_at=row.created_at,
                revoked_at=row.revoked_at,
            )
            for row in self._session.execute(statement)
        ]


def request_connector_queries() -> SqlConnectorQueries:
    """The read side on the current request's session (closed in teardown, see db.py)."""
    return SqlConnectorQueries(get_session())
