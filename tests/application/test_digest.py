import datetime
import json
from dataclasses import asdict

import pytest

from flightlog.application.digest import RULES_VERSION, digest, relative_path
from flightlog.contracts.digest import DigestEvent

T0 = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)
CWD = "/home/dev/work/shop"


def event(n: int, tool_name=None, file_path=None, command=None, type_="PostToolUse", cwd=CWD):
    return DigestEvent(
        id=n,
        type=type_,
        occurred_at=T0 + datetime.timedelta(minutes=n),
        tool_name=tool_name,
        file_path=file_path,
        command=command,
        cwd=cwd,
    )


def make(events, ended=T0 + datetime.timedelta(minutes=30)):
    return digest(7, events, started_at=T0, ended_at=ended)


def test_counts_edits_test_runs_and_tool_calls():
    result = make(
        [
            event(0, type_="SessionStart"),
            event(1, "Edit", f"{CWD}/src/cart.py"),
            event(2, "Write", f"{CWD}/tests/test_cart.py"),
            event(3, "Bash", command="pytest -q"),
            event(4, "Bash", command="ls"),
            event(5, "Read", f"{CWD}/README.md"),
            event(6, type_="SessionEnd"),
        ]
    )

    assert (result.edits, result.test_runs, result.tool_calls) == (2, 1, 5)
    assert result.tools == {"Bash": 2, "Edit": 1, "Read": 1, "Write": 1}
    assert result.files_touched == ["src/cart.py", "tests/test_cart.py"]
    assert result.duration_seconds == 30 * 60
    assert (result.agent_session_id, result.event_count) == (7, 7)
    assert result.rules_version == RULES_VERSION


def test_files_are_distinct_and_sorted():
    result = make(
        [
            event(1, "Edit", f"{CWD}/b.py"),
            event(2, "Edit", f"{CWD}/a.py"),
            event(3, "Edit", f"{CWD}/b.py"),
        ]
    )

    assert result.files_touched == ["a.py", "b.py"]
    assert result.edits == 3


def test_paths_outside_the_repo_are_counted_not_named():
    result = make([event(1, "Edit", "/home/dev/.bashrc"), event(2, "Edit", "/etc/hosts")])

    assert result.files_touched == []
    assert result.files_outside_repo == 2


def test_an_active_session_has_no_duration_yet():
    assert make([event(1)], ended=None).duration_seconds is None


@pytest.mark.parametrize(
    ("path", "cwd", "expected"),
    [
        ("/home/dev/work/shop/src/a.py", "/home/dev/work/shop", "src/a.py"),
        ("/home/dev/work/shop/src/a.py", "/home/dev/work/shop/", "src/a.py"),
        ("C:\\Users\\dev\\shop\\src\\a.py", "C:\\Users\\dev\\shop", "src/a.py"),
        ("c:\\users\\dev\\shop\\a.py", "C:\\Users\\dev\\shop", "a.py"),  # Windows ignores case
        ("src/a.py", "/home/dev/work/shop", "src/a.py"),  # already relative
        ("./src/a.py", "/home/dev/work/shop", "src/a.py"),
        ("/home/dev/work/shopping/a.py", "/home/dev/work/shop", None),  # a sibling, not inside
        ("/home/dev/work/shop/../secrets.txt", "/home/dev/work/shop", None),
        ("../secrets.txt", "/home/dev/work/shop", None),
        ("/etc/hosts", None, None),  # no cwd: nothing counts as inside
    ],
)
def test_relative_path(path, cwd, expected):
    assert relative_path(path, cwd) == expected


def test_the_digest_holds_no_raw_tool_input():
    """M5 acceptance: commands, content, URLs and responses never reach the stored digest."""
    secrets = [
        "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123",
        "s3cr3t-password",
        "https://example.com/?token=leaky",
        "ignore previous instructions",
        "/home/dev",  # the user's home directory
    ]
    events = [
        event(1, "Bash", command=f"{secrets[0]} pytest --password {secrets[1]}"),
        event(2, "WebFetch", command=None, file_path=None),
        event(3, "Edit", f"{CWD}/src/notes.py"),
        event(4, "Edit", "/home/dev/.netrc"),
        event(5, "Bash", command=f"curl '{secrets[2]}'  # {secrets[3]}"),
    ]

    stored = json.dumps(asdict(make(events)))

    for secret in secrets:
        assert secret not in stored
    assert "src/notes.py" in stored
