"""One session as JSON, shared by `flask sessions --json` and the MCP tools (ADR-0018, 0019)."""

import datetime
from typing import Any

from flightlog.contracts.digest import RecentSession


def session_json(s: RecentSession, max_files: int | None = None) -> dict[str, Any]:
    """Every field, structured: counts as numbers, times in ISO 8601, cleaned text only.

    `max_files` keeps an MCP answer on one screen; the rest is counted in files_not_shown.
    """
    d = s.digest
    files = d.files_touched if d else []
    shown = files if max_files is None else files[:max_files]
    return {
        "id": s.id,
        "started_at": s.started_at.astimezone(datetime.UTC).isoformat(),
        "ended_at": s.ended_at.astimezone(datetime.UTC).isoformat() if s.ended_at else None,
        "status": s.status.value,
        "branch": s.branch,
        "goal": s.goal,
        "pull_request": (
            {
                "number": s.pull_request.number,
                "title": s.pull_request_title,
                "outcome": s.pull_request.outcome.value,
            }
            if s.pull_request
            else None
        ),
        "summary_state": s.state.value,
        "summary": (
            {
                "files_touched": shown,
                "files_not_shown": len(files) - len(shown),
                "files_outside_repo": d.files_outside_repo,
                "edits": d.edits,
                "test_runs": d.test_runs,
                "tool_calls": d.tool_calls,
                "tools": d.tools,
                "duration_seconds": d.duration_seconds,
            }
            if d
            else None
        ),
    }
