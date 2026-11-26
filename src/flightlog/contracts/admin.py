import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class FailedJob:
    """A job the worker gave up on (ADR-0008), as the admin page lists it."""

    job_id: int
    event_id: int
    kind: str
    source: str
    event_type: str
    occurred_at: datetime.datetime
    attempts: int
    last_error: str | None
    failed_at: datetime.datetime
