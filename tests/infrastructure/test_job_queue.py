import datetime

import pytest
from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session

from flightlog.application.jobs import JobKind
from flightlog.contracts.ingest import CLAUDE
from flightlog.domain import RecordedEvent
from flightlog.infrastructure.event_log import SqlEventLog
from flightlog.infrastructure.job_queue import SqlJobQueries, SqlJobQueue
from flightlog.infrastructure.tables import event_jobs

NOW = datetime.datetime(2026, 11, 15, 10, 0, tzinfo=datetime.UTC)


def queue_event(session: Session, delivery_id: str) -> int:
    """Record an event and queue its job, as ingest does. Returns the event id."""
    event = RecordedEvent(
        source=CLAUDE, delivery_id=delivery_id, type="PostToolUse", occurred_at=NOW, payload={}
    )
    event_id = SqlEventLog(session).add_if_new(event)
    SqlJobQueue(session).enqueue(event_id, JobKind.APPLY_TO_SESSION)
    return event_id


@pytest.mark.db
def test_a_due_job_is_claimed(db_session):
    event_id = queue_event(db_session, "d1")

    job = SqlJobQueue(db_session).claim_next()

    assert job is not None
    assert job.event_id == event_id
    assert job.kind is JobKind.APPLY_TO_SESSION
    assert job.attempts == 0


@pytest.mark.db
def test_an_empty_queue_gives_nothing(db_session):
    assert SqlJobQueue(db_session).claim_next() is None


@pytest.mark.db
@pytest.mark.parametrize(
    ("change", "case"),
    [
        ({"failed_at": NOW}, "given up on"),
        ({"available_at": text("now() + interval '1 minute'")}, "not due yet (retry backoff)"),
    ],
)
def test_a_job_that_is_not_due_is_not_claimed(db_session, change, case):
    queue_event(db_session, "d1")
    db_session.execute(update(event_jobs).values(**change))

    assert SqlJobQueue(db_session).claim_next() is None, case


@pytest.fixture
def committed(db_engine: Engine):
    """For tests that need real commits seen by several connections. Cleans up afterwards."""
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(
            text("TRUNCATE event_jobs, event_logs, agent_sessions RESTART IDENTITY CASCADE")
        )


@pytest.mark.db
def test_two_workers_at_the_same_time_claim_different_jobs(committed: Engine):
    with Session(committed) as setup:
        queue_event(setup, "d1")
        queue_event(setup, "d2")
        setup.commit()

    with (
        Session(committed) as worker_a,
        Session(committed) as worker_b,
        Session(committed) as worker_c,
    ):
        job_a = SqlJobQueue(worker_a).claim_next()  # A holds its row lock...
        job_b = SqlJobQueue(worker_b).claim_next()  # ...so B skips that row instead of waiting
        job_c = SqlJobQueue(worker_c).claim_next()  # both rows are locked by others

        assert job_a is not None and job_b is not None
        assert job_a.id != job_b.id
        assert job_c is None
        for worker in (worker_a, worker_b, worker_c):
            worker.rollback()


@pytest.mark.db
def test_a_worker_sees_its_own_claimed_job_again_until_it_completes_it(committed: Engine):
    """SKIP LOCKED only skips rows locked by *other* transactions. Hence one job per
    transaction: claim, apply, delete, commit, and only then the next."""
    with Session(committed) as setup:
        queue_event(setup, "d1")
        queue_event(setup, "d2")
        setup.commit()

    with Session(committed) as worker:
        first = SqlJobQueue(worker).claim_next()
        again = SqlJobQueue(worker).claim_next()

        assert again is not None and first is not None
        assert again.id == first.id
        worker.rollback()


def job_row(session: Session, job_id: int):
    return session.execute(select(event_jobs).where(event_jobs.c.id == job_id)).one_or_none()


@pytest.mark.db
def test_a_completed_job_is_deleted(db_session):
    queue_event(db_session, "d1")
    queue = SqlJobQueue(db_session)
    job = queue.claim_next()

    queue.complete(job)

    assert job_row(db_session, job.id) is None


@pytest.mark.db
def test_a_job_retried_later_counts_the_attempt_and_is_not_due_yet(db_session):
    queue_event(db_session, "d1")
    queue = SqlJobQueue(db_session)
    job = queue.claim_next()

    queue.retry_later(job, "ValueError: boom", datetime.timedelta(minutes=1))

    row = job_row(db_session, job.id)
    assert row.attempts == 1
    assert row.last_error == "ValueError: boom"
    assert row.failed_at is None
    assert queue.claim_next() is None  # due again in a minute, not now


@pytest.mark.db
def test_a_job_given_up_on_is_marked_failed_and_never_claimed_again(db_session):
    queue_event(db_session, "d1")
    queue = SqlJobQueue(db_session)
    job = queue.claim_next()

    queue.give_up(job, "ValueError: boom")

    row = job_row(db_session, job.id)
    assert row.attempts == 1
    assert row.failed_at is not None
    assert queue.claim_next() is None


def fail_job(session: Session, delivery_id: str, error: str = "KeyError: 'pull_request'") -> int:
    """A queued job the worker has given up on. Returns the job id."""
    queue_event(session, delivery_id)
    queue = SqlJobQueue(session)
    job = queue.claim_next()
    queue.give_up(job, error)
    return job.id


@pytest.mark.db
def test_a_retried_job_is_due_now_with_a_fresh_set_of_attempts(db_session):
    job_id = fail_job(db_session, "d1")
    queue = SqlJobQueue(db_session)

    assert queue.retry_now(job_id) is True

    row = job_row(db_session, job_id)
    assert row.failed_at is None
    assert row.attempts == 0
    assert row.last_error == "KeyError: 'pull_request'"  # kept until the next run
    claimed = queue.claim_next()
    assert claimed is not None and claimed.id == job_id


@pytest.mark.db
def test_only_a_failed_job_can_be_retried(db_session):
    queue_event(db_session, "d1")
    queue = SqlJobQueue(db_session)
    pending = queue.claim_next()
    queue.retry_later(pending, "ValueError: boom", datetime.timedelta(minutes=1))

    assert queue.retry_now(pending.id) is False
    assert queue.retry_now(999_999) is False
    assert job_row(db_session, pending.id).attempts == 1  # untouched


@pytest.mark.db
def test_retrying_twice_is_harmless(db_session):
    job_id = fail_job(db_session, "d1")
    queue = SqlJobQueue(db_session)

    assert queue.retry_now(job_id) is True
    assert queue.retry_now(job_id) is False


@pytest.mark.db
def test_failed_jobs_are_listed_with_their_event_newest_failure_first(db_session):
    first = fail_job(db_session, "d1", "ValueError: first")
    db_session.execute(
        update(event_jobs)
        .where(event_jobs.c.id == first)
        .values(failed_at=text("now() - interval '1 hour'"))
    )
    second = fail_job(db_session, "d2", "ValueError: second")
    queue_event(db_session, "d3")  # pending, not failed

    failed = SqlJobQueries(db_session).failed_jobs()

    assert [f.job_id for f in failed] == [second, first]
    assert failed[0].kind == JobKind.APPLY_TO_SESSION
    assert failed[0].source == CLAUDE
    assert failed[0].event_type == "PostToolUse"
    assert failed[0].occurred_at == NOW
    assert failed[0].attempts == 1
    assert failed[0].last_error == "ValueError: second"
