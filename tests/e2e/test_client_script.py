"""M5 acceptance: a script using the client answers a question across sessions and prints
only the result. It needs an API key and has no database access (ADR-0020).
"""

import os
import re
import subprocess
import sys

from tests.e2e.flows import AgentSessionScript, at, post_pull_request, run_worker
from tests.harness import REPO_ROOT

SCRIPT = REPO_ROOT / "client" / "examples" / "reverted_files.py"


def new_key(app) -> str:
    result = app.test_cli_runner().invoke(args=["connector", "create", "reverted-files-script"])
    assert result.exit_code == 0, result.output
    return re.search(r"fl_[0-9a-f]{8}_[A-Za-z0-9_-]{43}", result.output).group()


def run_script(live_server: str, key: str | None, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FLASK_", "FLIGHTLOG_"))}
    env["FLIGHTLOG_URL"] = live_server
    if key:
        env["FLIGHTLOG_API_KEY"] = key
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def edits(script: AgentSessionScript, *paths: str) -> AgentSessionScript:
    for n, path in enumerate(paths, start=1):
        script.edit(n, f"/work/flightlog/{path}")
    return script


def test_the_script_prints_only_the_files_behind_reverted_pull_requests(e2e_app, live_server):
    # Two sessions on feat/cart, whose PR #7 was merged and then reverted by #8...
    edits(
        AgentSessionScript(e2e_app, "cart-1", branch="feat/cart").start(0),
        "src/cart.py",
        "src/tax.py",
    ).end(20)
    edits(AgentSessionScript(e2e_app, "cart-2", branch="feat/cart").start(30), "src/cart.py").end(
        40
    )
    # ...and one on feat/search, merged and kept.
    edits(
        AgentSessionScript(e2e_app, "search", branch="feat/search").start(50), "src/search.py"
    ).end(60)
    post_pull_request(
        e2e_app, number=7, branch="feat/cart", state="closed", merged_at=at(70), action="closed"
    )
    post_pull_request(
        e2e_app,
        number=8,
        branch="revert-7-feat/cart",
        state="closed",
        merged_at=at(80),
        action="closed",
        body="Reverts tmaartent/flightlog#7",
    )
    post_pull_request(
        e2e_app, number=9, branch="feat/search", state="closed", merged_at=at(90), action="closed"
    )
    run_worker(e2e_app)  # applies everything and computes the summaries

    result = run_script(
        live_server, new_key(e2e_app), "--repo", "flightlog", "--since", "2026-11-01"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["2 src/cart.py", "1 src/tax.py"]


def test_without_a_key_the_client_refuses_to_start(live_server):
    result = run_script(live_server, None, "--repo", "flightlog", "--since", "2026-11-01")

    assert result.returncode != 0
    assert "FLIGHTLOG_API_KEY" in result.stderr


def test_a_revoked_key_gets_unauthorized(e2e_app, live_server):
    key = new_key(e2e_app)
    e2e_app.test_cli_runner().invoke(args=["connector", "revoke", "reverted-files-script"])

    result = run_script(live_server, key, "--repo", "flightlog", "--since", "2026-11-01")

    assert result.returncode != 0
    assert "Unauthorized" in result.stderr
