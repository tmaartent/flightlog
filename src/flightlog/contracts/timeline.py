import datetime
from dataclasses import dataclass
from enum import StrEnum

from flightlog.contracts.sessions import LinkedPullRequest, SessionSummary


@dataclass(frozen=True)
class SessionEvent:
    """One applied event of a session, with only the fields the timeline reads (ADR-0010).

    Never the tool's response: it is large, and it is raw text from files and web pages.
    """

    id: int
    type: str
    occurred_at: datetime.datetime
    tool_name: str | None = None
    file_path: str | None = None
    command: str | None = None


class TimelineEntryKind(StrEnum):
    EDIT = "edit"
    TEST_RUN = "test_run"
    TOOL_CALL = "tool_call"
    MARKER = "marker"  # the session starting, stopping or ending


@dataclass(frozen=True)
class TimelineEntry:
    occurred_at: datetime.datetime
    kind: TimelineEntryKind
    type: str
    tool_name: str | None
    file_path: str | None
    command: str | None  # with likely secrets masked


@dataclass(frozen=True)
class SessionTimeline:
    session: SessionSummary
    entries: list[TimelineEntry]  # in event order: occurred_at, then id
    files_touched: list[str]  # distinct, sorted
    test_runs: int
    pull_requests: list[LinkedPullRequest]
