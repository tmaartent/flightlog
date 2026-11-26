"""A typed client for Flightlog's read API (M5 task 4, ADR-0020).

For scripts that look across many past sessions: filter and count in Python, print only the
answer. Needs a connector key (`flask connector create <name>`); it never touches a database.
"""

from flightlog_client.client import (
    Flightlog,
    FlightlogError,
    NotFound,
    RateLimited,
    Transport,
    Unauthorized,
)
from flightlog_client.models import (
    Outcome,
    PullRequest,
    Session,
    SessionRow,
    Summary,
    SummaryState,
    Timeline,
    TimelineEntry,
)

__all__ = [
    "Flightlog",
    "FlightlogError",
    "NotFound",
    "Outcome",
    "PullRequest",
    "RateLimited",
    "Session",
    "SessionRow",
    "Summary",
    "SummaryState",
    "Timeline",
    "TimelineEntry",
    "Transport",
    "Unauthorized",
]
