"""Seeding the live server the way production data arrives: signed deliveries and the worker.

No raw SQL: the hook client's own request builder signs each Claude Code event, a GitHub
delivery is signed like GitHub signs it, and the worker applies them.
"""

import datetime
import itertools
import json

from flask import Flask
from flightlog_hook import build_request

from tests.github_util import pull_request_payload
from tests.util import make_signature

T0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.UTC)

_deliveries = itertools.count(1)


def at(minutes: int) -> datetime.datetime:
    return T0 + datetime.timedelta(minutes=minutes)


class AgentSessionScript:
    """One Claude Code session as a series of hook events, posted in order."""

    def __init__(
        self, app: Flask, session_id: str, repo: str = "flightlog", branch: str | None = None
    ) -> None:
        self._client = app.test_client()
        self._secret = app.config["CLAUDE_HOOK_SECRET"]
        self.session_id = session_id
        self.cwd = f"/work/{repo}"
        self.branch = branch

    def event(self, name: str, minutes: int, **fields) -> "AgentSessionScript":
        hook = {
            "session_id": self.session_id,
            "hook_event_name": name,
            "cwd": self.cwd,
            **fields,
        }
        body, headers = build_request(
            self._secret, at(minutes), f"delivery-{next(_deliveries)}", hook, self.branch
        )
        response = self._client.post("/ingest/claude", data=body, headers=headers)
        assert response.status_code == 202, response.text
        return self

    def start(self, minutes: int = 0) -> "AgentSessionScript":
        return self.event("SessionStart", minutes)

    def edit(self, minutes: int, path: str) -> "AgentSessionScript":
        return self.event("PostToolUse", minutes, tool_name="Edit", tool_input={"file_path": path})

    def bash(self, minutes: int, command: str) -> "AgentSessionScript":
        return self.event("PostToolUse", minutes, tool_name="Bash", tool_input={"command": command})

    def end(self, minutes: int) -> "AgentSessionScript":
        return self.event("SessionEnd", minutes)


def post_pull_request(app: Flask, **fields) -> None:
    """A signed GitHub `pull_request` delivery; fields as in pull_request_payload."""
    body = json.dumps(pull_request_payload(**fields)).encode()
    response = app.test_client().post(
        "/ingest/github",
        data=body,
        content_type="application/json",
        headers={
            "X-Hub-Signature-256": make_signature(body, app.config["GITHUB_WEBHOOK_SECRET"]),
            "X-GitHub-Delivery": f"delivery-{next(_deliveries)}",
            "X-GitHub-Event": "pull_request",
        },
    )
    assert response.status_code == 202, response.text


def run_worker(app: Flask) -> None:
    """`flask worker --once`: apply everything queued, then stop."""
    result = app.test_cli_runner().invoke(args=["worker", "--once"])
    assert result.exit_code == 0, result.output
