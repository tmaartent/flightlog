import datetime
import io
import json
import urllib.error

import flightlog_hook
import pytest
from flightlog_hook import build_request

from tests.util import make_signature

NOW = datetime.datetime(2026, 11, 14, 10, 15, 30, 123456, tzinfo=datetime.UTC)
HOOK = {"session_id": "session-1", "hook_event_name": "Stop"}


def test_the_envelope_carries_delivery_id_timestamp_and_the_hook_input():
    body, _ = build_request("secret", NOW, "delivery-001", HOOK)

    assert json.loads(body) == {
        "delivery_id": "delivery-001",
        "occurred_at": "2026-11-14T10:15:30.123456+00:00",
        "hook": HOOK,
    }


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
