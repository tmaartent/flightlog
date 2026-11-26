from flightlog.application.jobs import Job, JobKind
from flightlog.application.retry import retry_failed_job
from tests.application.fakes import FakeUnitOfWork


def test_a_failed_job_is_queued_again_and_committed():
    uow = FakeUnitOfWork()
    uow.jobs.failed.append(Job(7, 70, JobKind.APPLY_TO_SESSION, attempts=5))

    assert retry_failed_job(7, uow) is True
    assert uow.jobs.failed == []
    assert uow.jobs.enqueued == [Job(7, 70, JobKind.APPLY_TO_SESSION, attempts=0)]
    assert uow.commits == 1


def test_a_job_that_is_not_failed_is_left_alone():
    uow = FakeUnitOfWork()
    uow.jobs.enqueue(70, JobKind.APPLY_TO_SESSION)

    assert retry_failed_job(1, uow) is False
    assert retry_failed_job(99, uow) is False
    assert len(uow.jobs.enqueued) == 1
