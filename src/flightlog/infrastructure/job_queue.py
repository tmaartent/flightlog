from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from flightlog.application.jobs import Job, JobKind
from flightlog.infrastructure.tables import event_jobs


class SqlJobQueue:
    """JobQueue on PostgreSQL: the event_jobs table, claimed with FOR UPDATE SKIP LOCKED."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, event_id: int, kind: JobKind) -> None:
        self._session.execute(insert(event_jobs).values(event_log_id=event_id, kind=kind.value))

    def claim_next(self) -> Job | None:
        # SQL expressions, not Python: `column is None` would be evaluated by Python (always
        # False) instead of becoming `IS NULL`. And the database's clock, not this process's.
        statement = (
            select(
                event_jobs.c.id, event_jobs.c.event_log_id, event_jobs.c.kind, event_jobs.c.attempts
            )
            .where(event_jobs.c.failed_at.is_(None), event_jobs.c.available_at <= func.now())
            .order_by(event_jobs.c.available_at, event_jobs.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return Job(
            id=row.id, event_id=row.event_log_id, kind=JobKind(row.kind), attempts=row.attempts
        )
