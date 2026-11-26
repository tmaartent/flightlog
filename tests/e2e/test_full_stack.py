"""End to end across processes (M4 task 5): hook script → flask run → worker → dashboard, and
a connector's key → read API → audit log. See ADR-0013, "The full stack".
"""

import json
import re
import shutil
import subprocess
import urllib.request
from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.stack import Stack
from tests.harness import E2E_DATABASE_URL, TEST_ADMIN_PASSWORD

KEY = re.compile(r"fl_[0-9a-f]{8}_[A-Za-z0-9_-]{43}")


@pytest.fixture(scope="module")
def stack(tmp_path_factory, e2e_app) -> Iterator[Stack]:
    """`flask run` once for this module; e2e_app has migrated the database it uses."""
    running = Stack(E2E_DATABASE_URL, tmp_path_factory.mktemp("stack") / "flask-run.log")
    running.start()
    yield running
    running.stop()


@pytest.fixture(autouse=True)
def server_log_on_failure(request, stack: Stack) -> Iterator[None]:
    """The server runs in another process: show what it logged when a test fails."""
    yield
    report = getattr(request.node, "report_call", None)
    if report is not None and report.failed:
        print("--- flask run log ---")
        print(stack.server_log())


@pytest.fixture
def git_repo(tmp_path):
    """A real checkout on a branch, as the agent's cwd: the hook script asks git for it."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "shop"
    repo.mkdir()
    for args in (["init", "-q", "-b", "feat/e2e"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(  # noqa: S603
            [git, "-c", "user.name=e2e", "-c", "user.email=e2e@example.com", *args],
            cwd=repo,
            check=True,
        )
    return repo


def log_in(page: Page, stack: Stack) -> None:
    page.goto(f"{stack.url}/login")
    page.get_by_label("Password").fill(TEST_ADMIN_PASSWORD)
    page.get_by_role("button", name="Log in").click()
    expect(page.get_by_role("button", name="Log out")).to_be_visible()


def agent_session(stack: Stack, cwd, session_id: str) -> None:
    """One short Claude Code session, every event through the real hook script."""
    base = {"session_id": session_id, "cwd": str(cwd)}
    stack.send_hook({**base, "hook_event_name": "SessionStart"})
    stack.send_hook(
        {
            **base,
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/shop/cart.py"},
        }
    )
    stack.send_hook({**base, "hook_event_name": "SessionEnd"})


def test_a_hook_event_reaches_the_dashboard(stack: Stack, git_repo, page: Page):
    agent_session(stack, git_repo, "7c1d0e2f-e2e")

    worker = stack.flask("worker", "--once")
    assert worker.returncode == 0

    log_in(page, stack)
    page.goto(f"{stack.url}/sessions")
    row = page.get_by_role("row").filter(has_text="7c1d0e2f")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("shop")
    expect(row).to_contain_text("feat/e2e")  # read from git by the hook script
    expect(row).to_contain_text("stopped")

    row.get_by_role("link", name="7c1d0e2f").click()
    files = page.get_by_role("region", name="Files touched")
    expect(files.get_by_role("listitem")).to_have_text(["src/shop/cart.py"])


def test_an_api_call_with_a_new_key_is_in_the_audit_log(stack: Stack, git_repo, page: Page):
    agent_session(stack, git_repo, "9a8b7c6d-e2e")
    stack.flask("worker", "--once")
    created = stack.flask("connector", "create", "e2e-script")
    key = KEY.search(created.stdout).group()

    request = urllib.request.Request(  # noqa: S310
        f"{stack.url}/api/v1/sessions", headers={"Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        body = json.load(response)
    assert [s["external_id"] for s in body["sessions"]] == ["9a8b7c6d-e2e"]
    assert body["sessions"][0]["branch"] == "feat/e2e"

    log_in(page, stack)
    page.goto(f"{stack.url}/admin/audit?connector=e2e-script")
    entry = page.get_by_role("row").filter(has_text="/api/v1/sessions")
    expect(entry).to_have_count(1)
    expect(entry).to_contain_text("e2e-script")
    expect(entry).to_contain_text("ok")
