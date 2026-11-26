"""A session's events read as a timeline (ADR-0010).

`classify` and `mask_secrets` are the rules that interpret Claude Code's hook payload; they are
pure functions, so every case is a one-line test.
"""

import re

from flightlog.application.ports import AgentSessionQueries
from flightlog.contracts.timeline import (
    SessionEvent,
    SessionTimeline,
    TimelineEntry,
    TimelineEntryKind,
)

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

# A Bash command is a test run when one of its steps starts with one of these. Wrappers that
# aren't listed (`make test`) are missed until they are added (ADR-0010).
TEST_COMMANDS = (
    "pytest",
    "python -m pytest",
    "uv run pytest",
    "npm test",
    "npm run test",
    "pnpm test",
    "yarn test",
    "go test",
    "cargo test",
    "mvn test",
    "./gradlew test",
)

# The steps of a shell line: `cd x && pytest`, `ruff check . ; pytest`, `pytest | tee log`.
_STEP_SEPARATOR = re.compile(r"&&|\|\||;|\|")
# Variables set for one command: `CI=1 pytest`, `DATABASE_URL=... pytest`.
_LEADING_ASSIGNMENTS = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")


def classify(event: SessionEvent) -> TimelineEntryKind:
    if event.tool_name is None:
        return TimelineEntryKind.MARKER
    if event.tool_name in EDIT_TOOLS:
        return TimelineEntryKind.EDIT
    if event.tool_name == "Bash" and event.command and _runs_tests(event.command):
        return TimelineEntryKind.TEST_RUN
    return TimelineEntryKind.TOOL_CALL


def _runs_tests(command: str) -> bool:
    for step in _STEP_SEPARATOR.split(command):
        step = _LEADING_ASSIGNMENTS.sub("", " ".join(step.split()))
        if any(step == test or step.startswith(test + " ") for test in TEST_COMMANDS):
            return True
    return False


MASK = "***"
_VALUE = r"""(?:'[^']*'|"[^"]*"|[^\s'"]+)"""

# Each pattern keeps what names the secret (group 1) and replaces only the secret itself.
_SECRET_PATTERNS = [
    # GITHUB_TOKEN=…, DB_PASSWORD='…', export API_KEY=…
    re.compile(
        r"\b([A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY|CREDENTIALS?)=)"
        + _VALUE,
        re.IGNORECASE,
    ),
    # --password=…, --token …, --with-token …
    re.compile(
        r"(--[A-Za-z-]*(?:token|password|passwd|secret|api-?key)(?:=|\s+))" + _VALUE,
        re.IGNORECASE,
    ),
    # Authorization: Bearer …, Authorization: token …, Authorization: …
    re.compile(r"(authorization:\s*(?:(?:bearer|basic|token)\s+)?)[^\s'\"]+", re.IGNORECASE),
    # https://user:password@host
    re.compile(r"(://[^/\s:@]+:)[^@\s/]+(?=@)"),
    # Flightlog's own API keys (ADR-0005): keep the prefix, it identifies the key, not more.
    re.compile(r"\b(fl_[A-Za-z0-9]+_)[A-Za-z0-9_-]+"),
    # Well-known token shapes without a name in front: GitHub and Anthropic keys.
    re.compile(r"()\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"()\bsk-ant-[A-Za-z0-9_-]+"),
]


def mask_secrets(command: str) -> str:
    """Hide likely secrets in a shell command. Best-effort: an unusual shape still shows."""
    for pattern in _SECRET_PATTERNS:
        command = pattern.sub(lambda match: match.group(1) + MASK, command)
    return command


def session_timeline(session_id: int, queries: AgentSessionQueries) -> SessionTimeline | None:
    """The session with its classified, masked events and linked PRs; None if unknown."""
    summary = queries.session_summary(session_id)
    if summary is None:
        return None

    entries = [
        TimelineEntry(
            occurred_at=event.occurred_at,
            kind=classify(event),
            type=event.type,
            tool_name=event.tool_name,
            file_path=event.file_path,
            command=mask_secrets(event.command) if event.command else event.command,
        )
        for event in queries.session_events(session_id)
    ]
    return SessionTimeline(
        session=summary,
        entries=entries,
        files_touched=sorted(
            {e.file_path for e in entries if e.kind is TimelineEntryKind.EDIT and e.file_path}
        ),
        test_runs=sum(1 for e in entries if e.kind is TimelineEntryKind.TEST_RUN),
        pull_requests=queries.linked_pull_requests(session_id),
    )
