import datetime
from dataclasses import dataclass
from enum import StrEnum

MAX_ATTEMPTS = 5
BASE_DELAY = datetime.timedelta(seconds=10)


def retry_delay(attempts: int) -> datetime.timedelta | None:
    """How long to wait before the next attempt, or None to give up."""

    if attempts <= MAX_ATTEMPTS:
        return BASE_DELAY * (2 ** (attempts - 1))
    return None


class JobKind(StrEnum):
    APPLY_TO_SESSION = "apply_to_session"


@dataclass(frozen=True)
class Job:
    """A unit of work for the worker: do `kind` for one recorded event."""

    id: int
    event_id: int
    kind: JobKind
    attempts: int
