"""The stored summary of a finished session (M5, ADR-0018).

Called a digest because `SessionSummary` already names a row of the session list. It holds
structured facts only: paths relative to the repo, counts and tool names. Never a command,
a prompt, file content or a tool's response: those can carry secrets and injected text.
"""

import datetime
from dataclasses import dataclass
from enum import StrEnum

from flightlog.contracts.sessions import LinkedPullRequest, SessionCursor
from flightlog.domain import AgentSessionStatus


@dataclass(frozen=True)
class DigestEvent:
    """What the digest reads from one applied event. The command is read, never stored."""

    id: int
    type: str
    occurred_at: datetime.datetime
    tool_name: str | None
    file_path: str | None
    command: str | None
    cwd: str | None


@dataclass(frozen=True)
class SessionDigest:
    agent_session_id: int
    files_touched: list[str]  # relative to the session's cwd, distinct, sorted
    files_outside_repo: int  # edits to paths outside cwd: counted, not named
    edits: int
    test_runs: int
    tool_calls: int
    tools: dict[str, int]  # tool name -> calls
    duration_seconds: int | None  # None while the session has no end
    event_count: int  # how many events it was computed from: a later digest has more
    rules_version: int


@dataclass(frozen=True)
class DigestedSession:
    """A session with its stored digest (if computed yet) and its linked PRs, as read."""

    id: int
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    status: AgentSessionStatus
    branch: str | None
    pull_requests: list[LinkedPullRequest]
    digest: SessionDigest | None


class SummaryState(StrEnum):
    READY = "ready"
    PENDING = "pending"  # stopped, the worker hasn't summarized it yet
    RUNNING = "running"  # still active: no summary until it ends


@dataclass(frozen=True)
class RecentSession:
    """One session as `flask sessions` and the MCP tools show it (ADR-0018)."""

    id: int
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    status: AgentSessionStatus
    branch: str | None
    goal: str | None  # the newest PR's title, or the branch made readable; cleaned text
    pull_request: LinkedPullRequest | None  # the newest linked PR
    pull_request_title: str | None  # its title, cleaned
    state: SummaryState
    digest: SessionDigest | None


@dataclass(frozen=True)
class SummaryFilter:
    """Which summaries the read API lists (ADR-0020): one repo, newest first, keyset-paged."""

    repo: str
    path: str | None = None  # only sessions whose digest lists this file
    since: datetime.datetime | None = None  # started at or after
    after: SessionCursor | None = None  # the end of the previous page
    limit: int = 25


@dataclass(frozen=True)
class SummaryPage:
    summaries: list[RecentSession]
    next_cursor: SessionCursor | None  # None on the last page
