from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from flightlog.contracts.audit import (
    AuditEntry,
    AuditFilter,
    AuditOutcome,
    AuditPage,
    AuditRecord,
)
from flightlog.infrastructure.db import get_session
from flightlog.infrastructure.tables import audit_log, connectors


class SqlAuditLog:
    """AuditLog on PostgreSQL, on a session of its own (ADR-0015).

    Not the request's session: after an error that one may be in a failed transaction, and a
    rollback of the request must not take the audit row with it.
    """

    def __init__(self, sessions: sessionmaker) -> None:
        self._sessions = sessions

    def record(self, entry: AuditEntry) -> None:
        with self._sessions() as session, session.begin():  # commits, or rolls back on error
            session.execute(
                audit_log.insert().values(
                    actor_kind=entry.actor_kind,
                    connector_id=entry.connector_id,
                    ip=entry.ip,
                    method=entry.method,
                    endpoint=entry.endpoint,
                    path=entry.path,
                    object_type=entry.object_type,
                    object_id=entry.object_id,
                    status=entry.status,
                )
            )


def _statuses(outcome: AuditOutcome):
    """The outcome as a condition on `status`: the SQL twin of AuditOutcome.of."""
    status = audit_log.c.status
    denied = status.in_([401, 403])
    return {
        AuditOutcome.OK: status < 400,
        AuditOutcome.DENIED: denied,
        AuditOutcome.LIMITED: status == 429,
        AuditOutcome.ERROR: (status >= 400) & ~denied & (status != 429),
    }[outcome]


class SqlAuditQueries:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_entries(self, audit_filter: AuditFilter) -> AuditPage:
        a = audit_log
        statement = (
            select(a, connectors.c.name.label("connector_name"))
            .outerjoin(connectors, connectors.c.id == a.c.connector_id)
            .order_by(a.c.id.desc())  # ids grow with time, and they are unique
        )
        if audit_filter.connector is not None:
            statement = statement.where(connectors.c.name == audit_filter.connector)
        if audit_filter.outcome is not None:
            statement = statement.where(_statuses(audit_filter.outcome))
        if audit_filter.before is not None:
            statement = statement.where(a.c.id < audit_filter.before)

        rows = self._session.execute(statement.limit(audit_filter.limit + 1)).all()
        records = [
            AuditRecord(
                id=row.id,
                occurred_at=row.occurred_at,
                actor_kind=row.actor_kind,
                connector_name=row.connector_name,
                ip=row.ip,
                method=row.method,
                endpoint=row.endpoint,
                path=row.path,
                object_type=row.object_type,
                object_id=row.object_id,
                status=row.status,
            )
            for row in rows[: audit_filter.limit]
        ]
        has_more = len(rows) > audit_filter.limit
        return AuditPage(records=records, next_before=records[-1].id if has_more else None)


def new_audit_log() -> SqlAuditLog:
    return SqlAuditLog(current_app.extensions["sessionmaker"])


def request_audit_queries() -> SqlAuditQueries:
    return SqlAuditQueries(get_session())
