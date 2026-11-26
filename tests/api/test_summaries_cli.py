"""`flask summaries rebuild` backfills digests through the worker (ADR-0018)."""

import pytest
from sqlalchemy import func, select

from flightlog.domain import AgentSessionStatus
from flightlog.infrastructure.tables import session_digests
from tests.session_util import add_event, add_started_session, at


@pytest.mark.db
def test_rebuild_queues_old_sessions_and_the_worker_summarizes_them(runner, db_session):
    for name in ["old-1", "old-2"]:
        session_id = add_started_session(db_session, name, status=AgentSessionStatus.STOPPED)
        add_event(db_session, name, at(1), session_id=session_id)

    first = runner.invoke(args=["summaries", "rebuild"])
    again = runner.invoke(args=["summaries", "rebuild"])  # jobs still queued: nothing new
    worker = runner.invoke(args=["worker", "--once"])

    assert first.exit_code == 0, first.output
    assert "Queued 2 session summaries" in first.output
    assert "Queued 0 session summaries" in again.output
    assert worker.exit_code == 0, worker.output
    assert db_session.scalar(select(func.count()).select_from(session_digests)) == 2
    assert "Queued 0" in runner.invoke(args=["summaries", "rebuild"]).output
