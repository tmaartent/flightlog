import datetime
import json
import signal
import threading
import time
import uuid

import pytest
from sqlalchemy import func, select

from flightlog.api.worker import register_signals, run
from flightlog.domain import AgentSession, AgentSessionStatus
from flightlog.infrastructure.tables import agent_sessions, event_jobs
from tests.claude_util import envelope, post_envelope

T0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.UTC)


def post_claude_event(
    client, event_name: str, occurred_at: datetime.datetime = T0, session_id: str = "session-1"
) -> None:
    """Send one hook event the way the hook client does: signed, through /ingest/claude."""
    hook = {"session_id": session_id, "hook_event_name": event_name, "cwd": "/work/flightlog"}

    body = json.dumps(envelope(hook, occurred_at, delivery_id=str(uuid.uuid4()))).encode()

    post_envelope(client, body)


@pytest.mark.db
def test_run_once_processes_the_queue(client, runner, db_session):
    post_claude_event(client, "SessionStart")

    assert db_session.scalar(select(func.count()).select_from(event_jobs)) == 1

    result = runner.invoke(args=["worker", "--once"])

    assert result.exit_code == 0, result.output
    assert db_session.scalar(select(func.count()).select_from(event_jobs)) == 0
    assert db_session.scalar(select(func.count()).select_from(agent_sessions)) == 1


@pytest.mark.db
def test_events_in_the_wrong_order_still_give_one_stopped_session(client, runner, db_session):
    post_claude_event(client, "SessionEnd", T0 + datetime.timedelta(minutes=5))
    post_claude_event(client, "PostToolUse", T0 + datetime.timedelta(minutes=1))
    post_claude_event(client, "SessionStart", T0)

    result = runner.invoke(args=["worker", "--once"])

    assert result.exit_code == 0, result.output
    session = db_session.scalars(select(AgentSession)).one()
    assert session.started_at == T0
    assert session.status is AgentSessionStatus.STOPPED


def test_a_stop_request_lets_the_current_job_finish_then_stops():
    stop = threading.Event()
    calls = []

    def process() -> bool:
        calls.append("job")
        stop.set()
        return True

    run(False, poll_interval=0, stop=stop, process=process)

    assert calls == ["job"]


def test_a_worker_that_is_already_stopped_takes_no_job():
    stop = threading.Event()
    stop.set()

    run(False, poll_interval=0, stop=stop, process=lambda: pytest.fail("took a job"))


def test_a_stop_request_wakes_an_idle_worker():
    stop = threading.Event()
    threading.Timer(0.05, stop.set).start()

    started = time.monotonic()
    run(False, poll_interval=50, stop=stop, process=lambda: False)

    assert time.monotonic() - started < 5


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_ctrl_c_and_sigterm_request_a_stop(signum, restore_signal_handlers):
    stop = threading.Event()
    register_signals(stop)

    signal.raise_signal(signum)

    assert stop.is_set()
