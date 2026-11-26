"""Reading a session's events as a timeline (ADR-0010): pure rules, fake queries."""

import datetime

import pytest

from flightlog.application.timeline import classify, mask_secrets, session_timeline
from flightlog.contracts.ingest import CLAUDE
from flightlog.contracts.sessions import LinkedPullRequest, PullRequestOutcome, SessionSummary
from flightlog.contracts.timeline import SessionEvent, TimelineEntryKind
from flightlog.domain import AgentSessionStatus
from tests.application.fakes import FakeAgentSessionQueries

T0 = datetime.datetime(2026, 11, 20, 9, 0, tzinfo=datetime.UTC)


def tool_event(tool_name: str, file_path: str | None = None, command: str | None = None):
    return SessionEvent(1, "PostToolUse", T0, tool_name, file_path, command)


@pytest.mark.parametrize("tool_name", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
def test_tools_that_change_a_file_are_edits(tool_name):
    assert classify(tool_event(tool_name, file_path="src/app.py")) is TimelineEntryKind.EDIT


@pytest.mark.parametrize("tool_name", ["Read", "Grep", "Glob", "WebFetch"])
def test_tools_that_only_look_are_plain_tool_calls(tool_name):
    assert classify(tool_event(tool_name)) is TimelineEntryKind.TOOL_CALL


@pytest.mark.parametrize(
    "command",
    [
        "pytest",
        "pytest -q tests/api",
        "python -m pytest",
        "npm test",
        "npm run test -- --watch=false",
        "uv run pytest -x",
        "cd /work/flightlog && pytest -q",
        "ruff check . && pytest",
        "  pytest  ",
        "CI=1 DATABASE_URL=postgresql://x pytest",
    ],
)
def test_bash_commands_that_run_tests_are_test_runs(command):
    assert classify(tool_event("Bash", command=command)) is TimelineEntryKind.TEST_RUN


@pytest.mark.parametrize(
    "command",
    ["ls", "pytestify", "echo pytest", "git commit -m 'run pytest'", "cat pytest.ini", ""],
)
def test_other_bash_commands_are_plain_tool_calls(command):
    assert classify(tool_event("Bash", command=command)) is TimelineEntryKind.TOOL_CALL


def test_a_bash_call_without_a_command_is_a_plain_tool_call():
    assert classify(tool_event("Bash", command=None)) is TimelineEntryKind.TOOL_CALL


@pytest.mark.parametrize("event_type", ["SessionStart", "Stop", "SessionEnd", "UserPromptSubmit"])
def test_events_without_a_tool_are_markers(event_type):
    assert classify(SessionEvent(1, event_type, T0)) is TimelineEntryKind.MARKER


@pytest.mark.parametrize(
    ("command", "masked"),
    [
        ("GITHUB_TOKEN=ghp_abc123 gh pr list", "GITHUB_TOKEN=*** gh pr list"),
        ("export API_KEY=s3cr3t", "export API_KEY=***"),
        ("DB_PASSWORD='hunter2' ./run.sh", "DB_PASSWORD=*** ./run.sh"),
        ("mysql --password=hunter2 -u root", "mysql --password=*** -u root"),
        ("login --token abc123 --verbose", "login --token *** --verbose"),
        (
            'curl -H "Authorization: Bearer eyJhbGciOi" https://x',
            'curl -H "Authorization: Bearer ***" https://x',
        ),
        ("curl -H 'authorization: token abc' x", "curl -H 'authorization: token ***' x"),
        ("curl -H 'Authorization: abc' x", "curl -H 'Authorization: ***' x"),
        ("curl -u x https://bob:hunter2@example.com", "curl -u x https://bob:***@example.com"),
        ("http :8000/api fl_ab12cd34_Zm9vYmFyYmF6", "http :8000/api fl_ab12cd34_***"),
        ("gh auth login --with-token ghp_1234567890abcdefghij", "gh auth login --with-token ***"),
    ],
)
def test_likely_secrets_are_masked(command, masked):
    assert mask_secrets(command) == masked


@pytest.mark.parametrize(
    "command",
    ["pytest -q", "git log --oneline -5", "KEYBOARD=us setxkbmap", "ls ~/.ssh", "echo $TOKEN"],
)
def test_commands_without_a_secret_are_unchanged(command):
    assert mask_secrets(command) == command


def summary(session_id: int = 1) -> SessionSummary:
    return SessionSummary(
        id=session_id,
        source=CLAUDE,
        external_id="session-1",
        repo="flightlog",
        branch="feat/x",
        status=AgentSessionStatus.STOPPED,
        started_at=T0,
        ended_at=T0 + datetime.timedelta(minutes=30),
        pending_events=0,
    )


def at(minutes: int) -> datetime.datetime:
    return T0 + datetime.timedelta(minutes=minutes)


def test_the_timeline_classifies_and_masks_the_events_in_order():
    queries = FakeAgentSessionQueries()
    queries.summaries[1] = summary()
    queries.events[1] = [
        SessionEvent(1, "SessionStart", at(0)),
        SessionEvent(2, "PostToolUse", at(1), "Edit", file_path="src/b.py"),
        SessionEvent(3, "PostToolUse", at(2), "Bash", command="TOKEN=abc pytest"),
        SessionEvent(4, "Stop", at(3)),
    ]

    timeline = session_timeline(1, queries)

    assert timeline is not None
    assert [e.kind for e in timeline.entries] == [
        TimelineEntryKind.MARKER,
        TimelineEntryKind.EDIT,
        TimelineEntryKind.TEST_RUN,
        TimelineEntryKind.MARKER,
    ]
    assert timeline.entries[2].command == "TOKEN=*** pytest"
    assert timeline.entries[1].file_path == "src/b.py"


def test_files_touched_are_the_distinct_edited_paths_sorted():
    queries = FakeAgentSessionQueries()
    queries.summaries[1] = summary()
    queries.events[1] = [
        SessionEvent(1, "PostToolUse", at(1), "Write", file_path="src/b.py"),
        SessionEvent(2, "PostToolUse", at(2), "Edit", file_path="src/a.py"),
        SessionEvent(3, "PostToolUse", at(3), "Edit", file_path="src/b.py"),
        SessionEvent(4, "PostToolUse", at(4), "Read", file_path="README.md"),
    ]

    timeline = session_timeline(1, queries)

    assert timeline is not None
    assert timeline.files_touched == ["src/a.py", "src/b.py"]


def test_test_runs_are_counted():
    queries = FakeAgentSessionQueries()
    queries.summaries[1] = summary()
    queries.events[1] = [
        SessionEvent(1, "PostToolUse", at(1), "Bash", command="pytest"),
        SessionEvent(2, "PostToolUse", at(2), "Bash", command="ls"),
        SessionEvent(3, "PostToolUse", at(3), "Bash", command="pytest -x"),
    ]

    timeline = session_timeline(1, queries)

    assert timeline is not None
    assert timeline.test_runs == 2


def test_the_timeline_carries_the_linked_pull_requests():
    queries = FakeAgentSessionQueries()
    queries.summaries[1] = summary()
    pr = LinkedPullRequest(7, "Add the dashboard", PullRequestOutcome.MERGED)
    queries.pull_requests[1] = [pr]

    timeline = session_timeline(1, queries)

    assert timeline is not None
    assert timeline.pull_requests == [pr]
    assert timeline.entries == []


def test_an_unknown_session_has_no_timeline():
    assert session_timeline(99, FakeAgentSessionQueries()) is None
