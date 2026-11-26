"""The stored summary of a finished session (M5, ADR-0018).

Called a digest because `SessionSummary` already names a row of the session list. It holds
structured facts only: paths relative to the repo, counts and tool names. Never a command,
a prompt, file content or a tool's response: those can carry secrets and injected text.
"""

import datetime
from dataclasses import dataclass


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
