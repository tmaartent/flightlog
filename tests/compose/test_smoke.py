"""Smoke test against `docker compose up` (M4 task 6, ADR-0017).

Skipped unless E2E_COMPOSE_URL points at a running stack, for example:

    FLIGHTLOG_DB_PORT=5434 FLIGHTLOG_APP_PORT=8001 FLASK_CLAUDE_HOOK_SECRET=smoke \\
        docker compose -p flightlog-smoke up -d --build --wait
    E2E_COMPOSE_URL=http://localhost:8001 E2E_COMPOSE_PROJECT=flightlog-smoke \\
        FLASK_CLAUDE_HOOK_SECRET=smoke pytest -m compose

Everything goes through the containers: the hook script posts to the app, the worker service
applies the events on its own, and the key comes from `flask connector create` in the app.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid

import pytest

from tests.harness import REPO_ROOT

URL = os.environ.get("E2E_COMPOSE_URL")
PROJECT = os.environ.get("E2E_COMPOSE_PROJECT", "flightlog")
HOOK_SECRET = os.environ.get("FLASK_CLAUDE_HOOK_SECRET", "")
WORKER_TIMEOUT = 30  # seconds for the worker service to apply the events

pytestmark = [
    pytest.mark.compose,
    pytest.mark.skipif(not URL, reason="needs a running stack: set E2E_COMPOSE_URL"),
]


def compose(*args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["docker", "compose", "-p", PROJECT, *args],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    return result.stdout


def get_json(path: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(f"{URL}{path}", headers=headers or {})  # noqa: S310
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        return response.status, dict(response.headers), json.load(response)


def send_hook(hook: dict) -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(REPO_ROOT / "scripts" / "flightlog_hook.py")],
        input=json.dumps(hook).encode(),
        env={**os.environ, "FLIGHTLOG_URL": URL, "CLAUDE_HOOK_SECRET": HOOK_SECRET},
        capture_output=True,
        timeout=30,
    )
    assert result.stderr.decode().strip() == "202", result.stderr.decode()


def test_the_app_is_up_and_reaches_the_database():
    status, _, body = get_json("/health")

    assert status == 200
    assert body == {"status": "ok", "db": "ok"}


def test_a_hook_event_is_applied_by_the_worker_service_and_read_through_the_api(tmp_path):
    session_id = f"smoke-{uuid.uuid4()}"
    cwd = tmp_path / "smoke-repo"
    cwd.mkdir()
    for event in ["SessionStart", "SessionEnd"]:
        send_hook({"session_id": session_id, "hook_event_name": event, "cwd": str(cwd)})

    name = f"smoke-{uuid.uuid4().hex[:8]}"
    flask = ["flask", "--app", "flightlog"]
    created = compose("exec", "-T", "app", *flask, "connector", "create", name)
    key = next(word for word in created.split() if word.startswith("fl_"))
    headers = {"Authorization": f"Bearer {key}"}

    deadline = time.monotonic() + WORKER_TIMEOUT
    while True:
        _, response_headers, body = get_json("/api/v1/sessions?repo=smoke-repo&limit=100", headers)
        found = [s for s in body["sessions"] if s["external_id"] == session_id]
        if found and found[0]["status"] == "stopped":
            break
        assert time.monotonic() < deadline, f"the worker didn't apply {session_id} in time"
        time.sleep(0.5)

    # The rate limiter counts in Redis, shared by gunicorn's workers (ADR-0014, ADR-0017).
    assert response_headers["X-RateLimit-Limit"] == "120"
    keys = compose("exec", "-T", "redis", "redis-cli", "--scan", "--pattern", "LIMIT*")
    assert keys.strip(), "no rate-limit counters in Redis"
