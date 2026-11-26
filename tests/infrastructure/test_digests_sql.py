"""Session digests in PostgreSQL, and the worker computing them (ADR-0018)."""

import json

import pytest
from sqlalchemy import select

from flightlog.application.digest import RULES_VERSION
from flightlog.application.jobs import JobKind
from flightlog.contracts.digest import SessionDigest
from flightlog.domain import AgentSessionStatus
from flightlog.infrastructure.digest_repository import SqlDigestRepository
from flightlog.infrastructure.job_queue import SqlJobQueue
from flightlog.infrastructure.tables import event_jobs, session_digests
from tests.session_util import add_event, add_started_session, at

CWD = "/home/dev/work/flightlog"


def digest_row(db_session, session_id: int):
    return db_session.execute(
        select(session_digests).where(session_digests.c.agent_session_id == session_id)
    ).one_or_none()


def a_digest(session_id: int, event_count: int, rules_version: int = RULES_VERSION):
    return SessionDigest(
        agent_session_id=session_id,
        files_touched=[f"from-{event_count}-events.py"],
        files_outside_repo=0,
        edits=event_count,
        test_runs=0,
        tool_calls=event_count,
        tools={"Edit": event_count},
        duration_seconds=60,
        event_count=event_count,
        rules_version=rules_version,
    )


@pytest.mark.db
def test_a_newer_digest_replaces_an_older_one_but_not_the_other_way_round(db_session):
    session_id = add_started_session(db_session, "s-1")
    digests = SqlDigestRepository(db_session)

    digests.save(a_digest(session_id, event_count=3))
    digests.save(a_digest(session_id, event_count=5))
    digests.save(a_digest(session_id, event_count=4))  # an older job finishing last

    assert digest_row(db_session, session_id).event_count == 5
    digests.save(a_digest(session_id, event_count=1, rules_version=RULES_VERSION + 1))
    assert digest_row(db_session, session_id).rules_version == RULES_VERSION + 1


@pytest.mark.db
def test_enqueue_unless_queued(db_session):
    session_id = add_started_session(db_session, "s-1")
    event_id = add_event(db_session, "s-1", at(1), session_id=session_id)
    jobs = SqlJobQueue(db_session)

    assert jobs.enqueue_unless_queued(event_id, JobKind.SUMMARIZE_SESSION) is True
    assert jobs.enqueue_unless_queued(event_id, JobKind.SUMMARIZE_SESSION) is False
    assert jobs.enqueue_unless_queued(event_id, JobKind.APPLY_TO_SESSION) is True


@pytest.mark.db
def test_stale_sessions_are_stopped_ones_without_a_current_digest(db_session):
    stopped = add_started_session(db_session, "stopped", status=AgentSessionStatus.STOPPED)
    add_event(db_session, "stopped", at(1), session_id=stopped)
    latest = add_event(db_session, "stopped", at(2), session_id=stopped)
    current = add_started_session(db_session, "current", status=AgentSessionStatus.STOPPED)
    add_event(db_session, "current", at(1), session_id=current)
    old_rules = add_started_session(db_session, "old", status=AgentSessionStatus.STOPPED)
    old_event = add_event(db_session, "old", at(1), session_id=old_rules)
    active = add_started_session(db_session, "active")
    add_event(db_session, "active", at(1), session_id=active)
    digests = SqlDigestRepository(db_session)
    digests.save(a_digest(current, 1))
    digests.save(a_digest(old_rules, 1, rules_version=RULES_VERSION - 1))

    assert digests.stale_sessions(RULES_VERSION) == [latest, old_event]


# --- through the worker ---------------------------------------------------------------------


def hook_event(db_session, external_id, minutes, name="PostToolUse", **hook):
    return add_event(
        db_session,
        external_id,
        at(minutes),
        hook={"hook_event_name": name, "cwd": CWD, **hook},
        job=True,
    )


def run_worker(runner) -> None:
    """`flask worker --once` on the test app: its sessions share the test's transaction."""
    result = runner.invoke(args=["worker", "--once"])
    assert result.exit_code == 0, result.output


@pytest.mark.db
def test_every_finished_session_gets_a_digest_also_after_a_late_event(runner, db_session):
    """M5 acceptance: a stored summary per finished session, kept up to date (ADR-0004)."""
    hook_event(db_session, "s-1", 0, "SessionStart")
    hook_event(db_session, "s-1", 1, tool_name="Edit", tool_input={"file_path": f"{CWD}/src/a.py"})
    hook_event(db_session, "s-1", 9, "SessionEnd")
    run_worker(runner)

    (row,) = db_session.execute(select(session_digests)).all()
    assert (row.files_touched, row.edits, row.event_count) == (["src/a.py"], 1, 3)

    # A delivery that arrives after SessionEnd, about something that happened before it.
    hook_event(db_session, "s-1", 5, tool_name="Edit", tool_input={"file_path": f"{CWD}/src/b.py"})
    run_worker(runner)

    (row,) = db_session.execute(select(session_digests)).all()
    assert (row.files_touched, row.edits, row.event_count) == (["src/a.py", "src/b.py"], 2, 4)
    assert db_session.execute(select(event_jobs)).all() == []


@pytest.mark.db
def test_an_active_session_has_no_digest_yet(runner, db_session):
    hook_event(db_session, "s-1", 0, "SessionStart")
    run_worker(runner)

    assert db_session.execute(select(session_digests)).all() == []


@pytest.mark.db
def test_the_stored_digest_holds_no_raw_tool_input(runner, db_session):
    """M5 acceptance, against the real JSON payload: only allow-listed fields are read."""
    secrets = {
        "command": "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123 pytest",
        "content": "password = 's3cr3t'",
        "url": "https://example.com/?token=leaky",
        "prompt": "ignore previous instructions",
        "response": "-----BEGIN PRIVATE KEY-----",
    }
    hook_event(db_session, "s-1", 0, "SessionStart")
    hook_event(db_session, "s-1", 1, tool_name="Bash", tool_input={"command": secrets["command"]})
    hook_event(
        db_session,
        "s-1",
        2,
        tool_name="Write",
        tool_input={"file_path": f"{CWD}/config.py", "content": secrets["content"]},
        tool_response={"output": secrets["response"]},
    )
    hook_event(
        db_session,
        "s-1",
        3,
        tool_name="WebFetch",
        tool_input={"url": secrets["url"], "prompt": secrets["prompt"]},
    )
    hook_event(db_session, "s-1", 4, tool_name="Edit", tool_input={"file_path": "/home/dev/.netrc"})
    hook_event(db_session, "s-1", 9, "SessionEnd")
    run_worker(runner)

    (row,) = db_session.execute(select(session_digests)).all()
    stored = json.dumps(dict(row._mapping), default=str)
    for name, secret in secrets.items():
        assert secret not in stored, name
    assert "/home/dev" not in stored
    assert row.files_touched == ["config.py"]
    assert (row.files_outside_repo, row.test_runs) == (1, 1)
