import datetime
from dataclasses import dataclass
from enum import StrEnum

from flightlog.contracts.ingest import CLAUDE, GITHUB

MAX_ATTEMPTS = 5
BASE_DELAY = datetime.timedelta(seconds=10)


def retry_delay(attempts: int) -> datetime.timedelta | None:
    """How long to wait before the next attempt, or None to give up."""

    if attempts <= MAX_ATTEMPTS:
        return BASE_DELAY * (2 ** (attempts - 1))
    return None


class JobKind(StrEnum):
    APPLY_TO_SESSION = "apply_to_session"
    APPLY_PULL_REQUEST = "apply_pull_request"
    SUMMARIZE_SESSION = "summarize_session"  # queued by apply_to_session (ADR-0018)


def jobs_for(source: str, event_type: str) -> list[JobKind]:
    """The work a new event needs. None for events Flightlog only records (push, for now)."""
    if source == CLAUDE:
        return [JobKind.APPLY_TO_SESSION]
    if source == GITHUB and event_type == "pull_request":
        return [JobKind.APPLY_PULL_REQUEST]
    return []


@dataclass(frozen=True)
class Job:
    """A unit of work for the worker: do `kind` for one recorded event."""

    id: int
    event_id: int
    kind: JobKind
    attempts: int
