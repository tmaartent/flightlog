"""`flask sessions --repo shop --last 5`: what agents did in this repo before (M5 task 2).

For an agent's shell: two lines per session, at most 120 characters each, so `--last 20`
still fits one screen. `--json` gives the same data, complete, for code (ADR-0018).
"""

import datetime
import json
import os
import sys
from typing import Any

import click
from flask import Blueprint, current_app

from flightlog.application.apply_to_session import repo_name
from flightlog.application.ports import DigestQueries
from flightlog.application.recent import clean_text, recent_sessions
from flightlog.contracts.digest import RecentSession, SummaryState

bp = Blueprint("sessions_cli", __name__, cli_group=None)

LINE_WIDTH = 120
TEXT_GOAL = 56  # the second line's budget: goal, the first file and the test runs
TEXT_PATH = 24
TEXT_BRANCH = 32


@bp.cli.command("sessions")
@click.option("--repo", help="The repo's folder name; default: the current folder's.")
@click.option("--last", type=click.IntRange(1, 20), default=5, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="All fields as JSON, for scripts.")
def sessions_command(repo: str | None, last: int, as_json: bool) -> None:
    """Recent agent sessions in a repo: when, what for, which files, and what came of it."""
    _utf8_stdout()
    repo = repo or repo_name(os.getcwd())
    queries: DigestQueries = current_app.extensions["digest_queries"]()
    found = recent_sessions(repo, last, queries)
    if as_json:
        click.echo(json.dumps([session_json(s) for s in found], indent=2))
        return
    if not found:
        click.echo(f"No agent sessions recorded for {repo} yet.")
        return
    click.echo(
        f"Last {len(found)} agent session{'s' if len(found) > 1 else ''} in {repo}, newest first:"
    )
    for session in found:
        for line in text_lines(session):
            click.echo(line[:LINE_WIDTH])


def _utf8_stdout() -> None:
    """Agents read this through a pipe. On Windows Python would write the console's code page
    (cp1252), which turns "·" into mojibake and fails outright on a "✓" in a PR title."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def text_lines(s: RecentSession) -> list[str]:
    started = s.started_at.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
    branch = clean_text(s.branch, TEXT_BRANCH) if s.branch else "no branch"
    pr = s.pull_request
    outcome = f"PR #{pr.number} {pr.outcome}" if pr else "no PR"
    first = f"{started} · {_duration(s)} · {branch} · {outcome}"

    goal = clean_text(s.goal, TEXT_GOAL) if s.goal else "—"
    if s.state is SummaryState.RUNNING:
        detail = "running now"
    elif s.digest is None:
        detail = "summary pending"
    else:
        detail = f"{_files(s.digest.files_touched)} · {_count(s.digest.test_runs, 'test run')}"
    return [first, f"  goal: {goal} · {detail}"]


def _duration(s: RecentSession) -> str:
    if s.ended_at is None:
        return "running"
    minutes = int((s.ended_at - s.started_at).total_seconds() // 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


def _files(paths: list[str]) -> str:
    if not paths:
        return "no files edited"
    first = paths[0] if len(paths[0]) <= TEXT_PATH else "…" + paths[0][-(TEXT_PATH - 1) :]
    more = f" +{len(paths) - 1}" if len(paths) > 1 else ""
    return f"{_count(len(paths), 'file')} ({first}{more})"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def session_json(s: RecentSession) -> dict[str, Any]:
    """Every field, structured: counts as numbers, times in ISO 8601, cleaned text only."""
    d = s.digest
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
                "files_touched": d.files_touched,
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
