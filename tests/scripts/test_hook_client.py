import datetime
import io
import json
import shutil
import subprocess
import urllib.error

import flightlog_hook
import pytest
from flightlog_hook import build_request, current_branch

from tests.util import make_signature

NOW = datetime.datetime(2026, 11, 14, 10, 15, 30, 123456, tzinfo=datetime.UTC)
HOOK = {"session_id": "session-1", "hook_event_name": "Stop"}


def test_the_envelope_carries_delivery_id_timestamp_and_the_hook_input():
    body, _ = build_request("secret", NOW, "delivery-001", HOOK)

    assert json.loads(body) == {
        "delivery_id": "delivery-001",
        "occurred_at": "2026-11-14T10:15:30.123456+00:00",
        "hook": HOOK,
        "git": {"branch": None},
    }


def test_the_envelope_carries_the_branch():
    body, _ = build_request("secret", NOW, "delivery-001", HOOK, branch="feat/link-prs")

    assert json.loads(body)["git"] == {"branch": "feat/link-prs"}


def test_the_body_is_signed_with_the_secret():
    body, headers = build_request("secret", NOW, "delivery-001", HOOK)

    assert headers["X-Flightlog-Signature"] == make_signature(body, "secret")
    assert headers["Content-Type"] == "application/json"


@pytest.fixture
def hook_env(monkeypatch):
    """main() with its environment set and the given stdin; returns the requests it sent."""
    monkeypatch.setenv("FLIGHTLOG_URL", "http://flightlog.test/")
    monkeypatch.setenv("CLAUDE_HOOK_SECRET", "secret")
    sent = []

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        sent.append((request, timeout))
        return Response()

    monkeypatch.setattr(flightlog_hook.urllib.request, "urlopen", fake_urlopen)

    def run(stdin: bytes):
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin)))
        flightlog_hook.main()
        return sent

    return run


def test_main_posts_the_signed_envelope_to_flightlog(hook_env):
    sent = hook_env(json.dumps(HOOK).encode())

    ((request, timeout),) = sent
    assert request.full_url == "http://flightlog.test/ingest/claude"
    assert request.get_method() == "POST"
    assert json.loads(request.data)["hook"] == HOOK
    assert request.get_header("X-flightlog-signature") == make_signature(request.data, "secret")
    assert timeout <= 2


def test_main_reads_utf8_input_whatever_the_console_code_page(hook_env):
    hook = {"hook_event_name": "PostToolUse", "cwd": "C:/Users/René/projecten"}

    ((request, _),) = hook_env(json.dumps(hook, ensure_ascii=False).encode("utf-8"))

    assert json.loads(request.data)["hook"]["cwd"] == "C:/Users/René/projecten"


@pytest.mark.parametrize(
    ("stdin", "case"),
    [(b"not json", "invalid JSON"), (b"[1, 2]", "not an object"), (b"", "empty input")],
)
def test_main_sends_nothing_and_does_not_raise_on_bad_input(hook_env, stdin, case):
    assert hook_env(stdin) == [], case


def test_main_does_not_raise_when_flightlog_is_down(hook_env, monkeypatch):
    def unreachable(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(flightlog_hook.urllib.request, "urlopen", unreachable)

    hook_env(json.dumps(HOOK).encode())  # must not raise


def test_main_does_nothing_without_configuration(monkeypatch):
    monkeypatch.delenv("FLIGHTLOG_URL", raising=False)
    monkeypatch.delenv("CLAUDE_HOOK_SECRET", raising=False)

    flightlog_hook.main()  # must not raise or read stdin


def test_main_only_talks_http(hook_env, monkeypatch):
    monkeypatch.setenv("FLIGHTLOG_URL", "file:///etc/passwd")

    assert hook_env(json.dumps(HOOK).encode()) == []


GIT = shutil.which("git")


def git(cwd, *args: str) -> None:
    subprocess.run([GIT, *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    """A repository with one commit, on branch main."""
    if GIT is None:
        pytest.skip("git is not installed")
    git(tmp_path, "init", "-b", "main")
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-m",
        "initial",
    )
    return tmp_path


def test_current_branch_is_the_checked_out_branch(git_repo):
    git(git_repo, "switch", "-c", "feat/link-prs")

    assert current_branch(git_repo) == "feat/link-prs"
    assert current_branch(str(git_repo)) == "feat/link-prs"


def test_current_branch_is_none_on_a_detached_head(git_repo):
    git(git_repo, "switch", "--detach")

    assert current_branch(git_repo) is None


def test_current_branch_is_none_outside_a_repository(tmp_path):
    assert current_branch(tmp_path) is None


@pytest.mark.parametrize("cwd", ["", "   ", "/does/not/exist"])
def test_current_branch_is_none_without_a_usable_folder(cwd):
    assert current_branch(cwd) is None


def test_current_branch_is_none_when_git_is_missing(git_repo, monkeypatch):
    monkeypatch.setattr(flightlog_hook.shutil, "which", lambda name: None)

    assert current_branch(git_repo) is None


def test_current_branch_is_none_when_git_is_too_slow(git_repo, monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr(flightlog_hook.subprocess, "run", slow)

    assert current_branch(git_repo) is None


def test_main_sends_the_branch_of_the_hook_cwd(hook_env, git_repo):
    hook = {**HOOK, "cwd": str(git_repo)}

    ((request, _),) = hook_env(json.dumps(hook).encode())

    assert json.loads(request.data)["git"] == {"branch": "main"}
