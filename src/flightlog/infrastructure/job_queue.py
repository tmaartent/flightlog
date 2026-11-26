import datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from flightlog.application.jobs import Job, JobKind
from flightlog.contracts.admin import FailedJob
from flightlog.infrastructure.db import get_session
from flightlog.infrastructure.tables import event_jobs, event_logs


class SqlJobQueue:
    """JobQueue on PostgreSQL: the event_jobs table, claimed with FOR UPDATE SKIP LOCKED."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(self, event_id: int, kind: JobKind) -> None:
        self._session.execute(insert(event_jobs).values(event_log_id=event_id, kind=kind.value))

    def enqueue_unless_queued(self, event_id: int, kind: JobKind) -> bool:
        # The unique (event_log_id, kind) decides, in one statement: no check-then-insert race.
        statement = (
            pg_insert(event_jobs)
            .values(event_log_id=event_id, kind=kind.value)
            .on_conflict_do_nothing(index_elements=["event_log_id", "kind"])
            .returning(event_jobs.c.id)
        )
        return self._session.scalar(statement) is not None

    def retry_later(self, job: Job, error: str, delay: datetime.timedelta) -> None:
        self._session.execute(
            update(event_jobs)
            .where(event_jobs.c.id == job.id)
            .values(
                attempts=job.attempts + 1,
                last_error=error,
                available_at=func.now() + delay,
            )
        )

    def give_up(self, job: Job, error: str) -> None:
        self._session.execute(
            update(event_jobs)
            .where(event_jobs.c.id == job.id)
            .values(
                attempts=job.attempts + 1,
                last_error=error,
                failed_at=func.now(),
            )
        )

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

    def complete(self, job: Job) -> None:
        self._session.execute(delete(event_jobs).where(event_jobs.c.id == job.id))

    def retry_now(self, job_id: int) -> bool:
        # One UPDATE with the condition in its WHERE: two clicks at once can't both succeed,
        # and a job that isn't failed (pending, or claimed by a worker) is never touched.
        result = self._session.execute(
            update(event_jobs)
            .where(event_jobs.c.id == job_id, event_jobs.c.failed_at.is_not(None))
            .values(failed_at=None, attempts=0, available_at=func.now())
        )
        return result.rowcount == 1


class SqlJobQueries:
    """JobQueries on PostgreSQL: failed jobs joined with their event, for the admin page."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def failed_jobs(self) -> list[FailedJob]:
        statement = (
            select(
                event_jobs.c.id,
                event_jobs.c.event_log_id,
                event_jobs.c.kind,
                event_logs.c.source,
                event_logs.c.type,
                event_logs.c.occurred_at,
                event_jobs.c.attempts,
                event_jobs.c.last_error,
                event_jobs.c.failed_at,
            )
            .join(event_logs, event_logs.c.id == event_jobs.c.event_log_id)
            .where(event_jobs.c.failed_at.is_not(None))
            .order_by(event_jobs.c.failed_at.desc(), event_jobs.c.id.desc())
        )
        return [
            FailedJob(
                job_id=row.id,
                event_id=row.event_log_id,
                kind=row.kind,
                source=row.source,
                event_type=row.type,
                occurred_at=row.occurred_at,
                attempts=row.attempts,
                last_error=row.last_error,
                failed_at=row.failed_at,
            )
            for row in self._session.execute(statement)
        ]


def request_job_queries() -> SqlJobQueries:
    """The queue's read side on the current request's session."""
    return SqlJobQueries(get_session())
