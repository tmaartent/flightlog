"""What the read API returns, as frozen dataclasses (ADR-0020).

The client's own types, not the server's: it doesn't depend on the flightlog package. A
contract test parses the server's real JSON with these, so the two can't drift silently.
Goals and pull request titles come from GitHub: data, never instructions.
"""

import datetime
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"
    REVERTED = "reverted"  # merged, and later undone by another merged PR


class SummaryState(StrEnum):
    READY = "ready"
    PENDING = "pending"  # the session stopped; the worker hasn't summarized it yet
    RUNNING = "running"  # the session is still active


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str | None
    outcome: Outcome


@dataclass(frozen=True)
class Summary:
    files_touched: list[str]  # relative to the repo
    files_not_shown: int
    files_outside_repo: int
    edits: int
    test_runs: int
    tool_calls: int
    tools: dict[str, int]
    duration_seconds: int | None


@dataclass(frozen=True)
class Session:
    """A session with its stored summary: what /summaries and the MCP tools return."""

    id: int
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    status: str
    branch: str | None
    goal: str | None
    pull_request: PullRequest | None
    summary_state: SummaryState
    summary: Summary | None


@dataclass(frozen=True)
class SessionRow:
    """A session as /sessions lists it: no summary, no pull request."""

    id: int
    source: str
    external_id: str
    repo: str
    branch: str | None
    status: str
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    pending_events: int


@dataclass(frozen=True)
class TimelineEntry:
    occurred_at: datetime.datetime
    kind: str
    type: str
    tool_name: str | None
    file_path: str | None
    command: str | None  # masked by the server, but still tool text: keep it out of prompts


@dataclass(frozen=True)
class Timeline:
    session: SessionRow
    pull_requests: list[PullRequest]
    files_touched: list[str]
    test_runs: int
    entries: list[TimelineEntry]


def _time(value: str | None) -> datetime.datetime | None:
    return datetime.datetime.fromisoformat(value) if value else None


def _pull_request(data: dict[str, Any] | None) -> PullRequest | None:
    if data is None:
        return None
    return PullRequest(data["number"], data.get("title"), Outcome(data["outcome"]))


def parse_session(data: dict[str, Any]) -> Session:
    summary = data.get("summary")
    return Session(
        id=data["id"],
        started_at=_time(data["started_at"]),
        ended_at=_time(data["ended_at"]),
        status=data["status"],
        branch=data["branch"],
        goal=data["goal"],
        pull_request=_pull_request(data["pull_request"]),
        summary_state=SummaryState(data["summary_state"]),
        summary=(
            Summary(
                files_touched=summary["files_touched"],
                files_not_shown=summary.get("files_not_shown", 0),
                files_outside_repo=summary["files_outside_repo"],
                edits=summary["edits"],
                test_runs=summary["test_runs"],
                tool_calls=summary["tool_calls"],
                tools=summary["tools"],
                duration_seconds=summary["duration_seconds"],
            )
            if summary
            else None
        ),
    )


def parse_session_row(data: dict[str, Any]) -> SessionRow:
    return SessionRow(
        id=data["id"],
        source=data["source"],
        external_id=data["external_id"],
        repo=data["repo"],
        branch=data["branch"],
        status=data["status"],
        started_at=_time(data["started_at"]),
        ended_at=_time(data["ended_at"]),
        pending_events=data["pending_events"],
    )


def parse_timeline(data: dict[str, Any]) -> Timeline:
    return Timeline(
        session=parse_session_row(data["session"]),
        pull_requests=[_pull_request(pr) for pr in data["pull_requests"]],
        files_touched=data["files_touched"],
        test_runs=data["test_runs"],
        entries=[
            TimelineEntry(
                occurred_at=_time(e["occurred_at"]),
                kind=e["kind"],
                type=e["type"],
                tool_name=e["tool_name"],
                file_path=e["file_path"],
                command=e["command"],
            )
            for e in data["entries"]
        ],
    )
