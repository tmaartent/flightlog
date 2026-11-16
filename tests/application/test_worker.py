"""The worker's orchestration on the fake unit of work, with stand-in handlers."""

import datetime

from flightlog.application.jobs import BASE_DELAY, MAX_ATTEMPTS, JobKind
from flightlog.application.worker import process_one_job
from tests.application.fakes import FakeUnitOfWork

NOW = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.UTC)


def succeeding(event_id: int, now: datetime.datetime, uow: FakeUnitOfWork) -> None:
    pass


def failing(event_id: int, now: datetime.datetime, uow: FakeUnitOfWork) -> None:
    raise ValueError("Foo")


def test_process_one_job_handles_the_job_completes_it_and_commits():
    uow = FakeUnitOfWork()
    uow.jobs.enqueue(10, JobKind.APPLY_TO_SESSION)
    called = []

    def handle(event_id: int, now: datetime.datetime, uow: FakeUnitOfWork) -> None:
        called.append((event_id, now))

    assert process_one_job(lambda: uow, NOW, {JobKind.APPLY_TO_SESSION: handle})

    assert called == [(10, NOW)]
    assert uow.jobs.claim_next() is None
    assert uow.commits == 1


def test_process_one_job_rolls_back_and_retries_if_max_attempts_not_exceeded():
    uow = FakeUnitOfWork()
    uow.jobs.enqueue(10, JobKind.APPLY_TO_SESSION)

    # True: a job was claimed, so the loop goes on to the next one instead of sleeping.
    assert process_one_job(lambda: uow, NOW, {JobKind.APPLY_TO_SESSION: failing})

    assert len(uow.jobs.enqueued) == 1
    assert uow.rollbacks == 1
    assert uow.commits == 1  # the recorded attempt is saved
    assert uow.jobs.latest_error == "ValueError: Foo"
    assert uow.jobs.delay == BASE_DELAY
    assert not uow.jobs.given_up


def test_process_one_job_rolls_back_and_gives_up_if_max_attempts_exceeded():
    uow = FakeUnitOfWork()
    uow.jobs.enqueue(10, JobKind.APPLY_TO_SESSION, attempts=MAX_ATTEMPTS)

    assert process_one_job(lambda: uow, NOW, {JobKind.APPLY_TO_SESSION: failing})

    assert len(uow.jobs.enqueued) == 1
    assert uow.rollbacks == 1
    assert uow.commits == 1
    assert uow.jobs.latest_error == "ValueError: Foo"
    assert uow.jobs.given_up


def test_a_job_without_a_handler_is_retried_not_crashing_the_worker():
    uow = FakeUnitOfWork()
    uow.jobs.enqueue(10, JobKind.APPLY_TO_SESSION)

    assert process_one_job(lambda: uow, NOW, handlers={})

    assert uow.jobs.latest_error is not None
    assert uow.jobs.latest_error.startswith("KeyError")


def test_process_one_job_returns_false_when_no_jobs_to_claim():
    uow = FakeUnitOfWork()

    assert not process_one_job(lambda: uow, NOW, {JobKind.APPLY_TO_SESSION: succeeding})
    assert uow.commits == 0
