import datetime
import logging
from collections.abc import Callable, Mapping

from flightlog.application.apply_pull_request import apply_pull_request
from flightlog.application.apply_to_session import apply_to_session
from flightlog.application.jobs import JobKind, retry_delay
from flightlog.application.ports import UnitOfWork

Handler = Callable[[int, datetime.datetime, UnitOfWork], None]
HANDLERS: Mapping[JobKind, Handler] = {
    JobKind.APPLY_TO_SESSION: apply_to_session,
    JobKind.APPLY_PULL_REQUEST: apply_pull_request,
}

logger = logging.getLogger(__name__)


def process_one_job(
    new_uow: Callable[[], UnitOfWork],
    now: datetime.datetime,
    handlers: Mapping[JobKind, Handler] = HANDLERS,
) -> bool:
    """Claim one due job and run its handler. True if a job was claimed, even if it failed.

    Success: the handler's changes and the job's deletion are committed together. Failure:
    roll back, then record the attempt (retry later, or give up after MAX_ATTEMPTS) in a new
    transaction. The row lock is released in between, so another worker may claim the job
    first; jobs are processed at least once and handlers are idempotent (ADR-0008).
    """
    with new_uow() as uow:
        job = uow.jobs.claim_next()

        if job:
            try:
                handlers[job.kind](job.event_id, now, uow)
                uow.jobs.complete(job)
                uow.commit()
            except Exception as e:
                uow.rollback()
                logger.exception("job %s (%s) failed", job.id, job.kind)
                error = f"{type(e).__name__}: {e}"

                delay = retry_delay(job.attempts + 1)
                if delay is not None:
                    uow.jobs.retry_later(job, error, delay)
                else:
                    uow.jobs.give_up(job, error)

                uow.commit()

            return True
        else:
            return False
