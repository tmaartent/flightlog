"""The whole stack as separate processes, started the way production starts them (ADR-0013).

`flask run` serves the app, configured only by FLASK_* variables; the hook script reads a hook
event on stdin like Claude Code calls it; `flask worker --once` and `flask connector create` run
as their own processes. Nothing is imported into the test process except the URL.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from tests.harness import (
    REPO_ROOT,
    TEST_ADMIN_PASSWORD_HASH,
    TEST_CLAUDE_SECRET,
    TEST_GITHUB_SECRET,
)

HOOK_SCRIPT = REPO_ROOT / "scripts" / "flightlog_hook.py"
STARTUP_TIMEOUT = 15  # seconds until /health must answer


def free_port() -> int:
    """A port nobody listens on right now (the OS picks it; a tiny race, fine for tests)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def flask_environment(database_url: str) -> dict[str, str]:
    """Config as production gets it: environment variables, read by from_prefixed_env()."""
    return {
        **os.environ,
        "FLASK_SKIP_DOTENV": "1",  # never the developer's .env, which points at the dev DB
        "FLASK_DATABASE_URL": database_url,
        "FLASK_SECRET_KEY": "e2e-secret-key",
        "FLASK_ADMIN_PASSWORD_HASH": TEST_ADMIN_PASSWORD_HASH,
        "FLASK_CLAUDE_HOOK_SECRET": TEST_CLAUDE_SECRET,
        "FLASK_GITHUB_WEBHOOK_SECRET": TEST_GITHUB_SECRET,
        "FLASK_SESSION_COOKIE_SECURE": "false",  # parsed as JSON: plain http to localhost
        "PYTHONIOENCODING": "utf-8",
    }


class Stack:
    def __init__(self, database_url: str, log_path: Path) -> None:
        self.env = flask_environment(database_url)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log_path = log_path
        self._server: subprocess.Popen | None = None

    # --- the app server -------------------------------------------------------------------

    def start(self) -> None:
        self._log = self.log_path.open("w", encoding="utf-8")
        self._server = subprocess.Popen(
            [sys.executable, "-m", "flask", "--app", "flightlog", "run", "--port", str(self.port)],
            env=self.env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._server.poll() is not None:
                raise RuntimeError(f"flask run exited early:\n{self.server_log()}")
            try:
                with urllib.request.urlopen(f"{self.url}/health", timeout=1) as response:  # noqa: S310
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"flask run did not answer /health in time:\n{self.server_log()}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.terminate()
            try:
                self._server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server.kill()
                self._server.wait()
        self._log.close()

    def server_log(self) -> str:
        self._log.flush()
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    # --- the other processes --------------------------------------------------------------

    def flask(self, *args: str) -> subprocess.CompletedProcess:
        """`flask --app flightlog <args>` as its own process, with the server's config."""
        result = subprocess.run(
            [sys.executable, "-m", "flask", "--app", "flightlog", *args],
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        assert result.returncode == 0, f"flask {' '.join(args)} failed:\n{result.stderr}"
        return result

    def send_hook(self, hook: dict) -> None:
        """Run the hook script as Claude Code does: hook JSON on stdin, config in the env.

        It always exits 0, so "did it arrive" is the server's answer, which it prints.
        """
        result = subprocess.run(
            [sys.executable, str(HOOK_SCRIPT)],
            input=json.dumps(hook).encode(),
            env={
                **os.environ,
                "FLIGHTLOG_URL": self.url,
                "CLAUDE_HOOK_SECRET": TEST_CLAUDE_SECRET,
            },
            capture_output=True,
            timeout=30,
        )
        assert result.stderr.decode().strip() == "202", result.stderr.decode()
