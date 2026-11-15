from dataclasses import dataclass
from enum import StrEnum


class JobKind(StrEnum):
    APPLY_TO_SESSION = "apply_to_session"


@dataclass(frozen=True)
class Job:
    """A unit of work for the worker: do `kind` for one recorded event."""

    id: int
    event_id: int
    kind: JobKind
    attempts: int
