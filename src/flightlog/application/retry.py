from flightlog.application.ports import UnitOfWork


def retry_failed_job(job_id: int, uow: UnitOfWork) -> bool:
    """Queue a failed job again, due now, with a fresh set of attempts (ADR-0012).

    False when there is no failed job with this id: it was retried already (a double click,
    two tabs), or it never failed. Nothing changes then, so retrying twice is harmless.
    """
    retried = uow.jobs.retry_now(job_id)
    uow.commit()
    return retried
