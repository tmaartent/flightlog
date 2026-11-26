"""The stored summary of a session (M5 task 1, ADR-0018): computed once, from its events.

Edits and test runs are counted with the timeline's `classify`, so every view agrees. What
is kept is an allow-list: paths inside the repo, counts and tool names. A command is read
to recognise a test run and then dropped.
"""

import datetime
import posixpath
from collections import Counter

from flightlog.application.jobs import JobKind
from flightlog.application.ports import UnitOfWork
from flightlog.application.timeline import classify
from flightlog.contracts.digest import DigestEvent, SessionDigest
from flightlog.contracts.timeline import SessionEvent, TimelineEntryKind

# Bump when the counting rules change (a new test command, a new edit tool), then run
# `flask summaries rebuild`: digests with an older version are computed again.
RULES_VERSION = 1


def digest(
    agent_session_id: int,
    events: list[DigestEvent],
    started_at: datetime.datetime,
    ended_at: datetime.datetime | None,
) -> SessionDigest:
    files: set[str] = set()
    outside = edits = test_runs = 0
    tools: Counter[str] = Counter()
    for event in events:
        kind = classify(
            SessionEvent(
                event.id,
                event.type,
                event.occurred_at,
                tool_name=event.tool_name,
                file_path=event.file_path,
                command=event.command,
            )
        )
        if event.tool_name:
            tools[event.tool_name] += 1
        if kind is TimelineEntryKind.TEST_RUN:
            test_runs += 1
        elif kind is TimelineEntryKind.EDIT and event.file_path:
            edits += 1
            path = relative_path(event.file_path, event.cwd)
            if path is None:
                outside += 1
            else:
                files.add(path)

    return SessionDigest(
        agent_session_id=agent_session_id,
        files_touched=sorted(files),
        files_outside_repo=outside,
        edits=edits,
        test_runs=test_runs,
        tool_calls=sum(tools.values()),
        tools=dict(sorted(tools.items())),
        duration_seconds=int((ended_at - started_at).total_seconds()) if ended_at else None,
        event_count=len(events),
        rules_version=RULES_VERSION,
    )


def relative_path(path: str, cwd: str | None) -> str | None:
    """The path relative to cwd, or None when it is outside it (or there is no cwd).

    Claude Code sends absolute paths: relative ones keep home directories and user names out
    of the digest, and line up across machines. Windows paths compare without case.
    """
    path = path.replace("\\", "/")
    windows = len(path) > 1 and path[1] == ":"
    if not path.startswith("/") and not windows:
        relative = posixpath.normpath(path)
    else:
        if not cwd:
            return None
        root = cwd.replace("\\", "/").rstrip("/")
        absolute = posixpath.normpath(path)
        compare_path, compare_root = (
            (absolute.lower(), root.lower()) if windows else (absolute, root)
        )
        if not compare_path.startswith(compare_root + "/"):
            return None
        relative = absolute[len(root) + 1 :]
    if relative == ".." or relative.startswith("../"):
        return None
    return relative


def summarize_session(event_id: int, now: datetime.datetime, uow: UnitOfWork) -> None:
    """The `summarize_session` job: compute the session's digest and store it (an upsert).

    Enqueued when SessionEnd is applied, and for every event applied to a stopped session
    after that (a late delivery, ADR-0004). Safe to run twice and in any order: the store
    keeps the digest computed from the most events (ADR-0018). Does not commit.
    """
    event = uow.events.get(event_id)
    if event is None:
        raise LookupError(f"event {event_id} does not exist")
    if event.agent_session_id is None:
        return  # not a session's event: nothing to summarize
    session = uow.digests.session(event.agent_session_id)
    if session is None:
        raise LookupError(f"session {event.agent_session_id} does not exist")
    started_at, ended_at = session
    events = uow.digests.source_events(event.agent_session_id)
    uow.digests.save(digest(event.agent_session_id, events, started_at, ended_at))


def rebuild_digests(uow: UnitOfWork) -> int:
    """Queue a summarize job for every stopped session without a current digest. Commits."""
    queued = 0
    for event_id in uow.digests.stale_sessions(RULES_VERSION):
        if uow.jobs.enqueue_unless_queued(event_id, JobKind.SUMMARIZE_SESSION):
            queued += 1
    uow.commit()
    return queued
