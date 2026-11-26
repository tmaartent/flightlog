"""Seeding sessions and their events in a test's database session."""

import datetime
import itertools

from flightlog.application.jobs import JobKind
from flightlog.contracts.ingest import CLAUDE
from flightlog.domain import AgentSession, AgentSessionStatus, RecordedEvent
from flightlog.infrastructure.job_queue import SqlJobQueue

T0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.UTC)
_delivery_ids = itertools.count(1)


def at(minutes: int) -> datetime.datetime:
    return T0 + datetime.timedelta(minutes=minutes)


def add_started_session(
    db_session,
    external_id: str,
    started_at: datetime.datetime = T0,
    repo: str = "flightlog",
    status: AgentSessionStatus = AgentSessionStatus.ACTIVE,
    branch: str | None = None,
) -> int:
    session = AgentSession(CLAUDE, external_id, repo, started_at, branch=branch, status=status)
    db_session.add(session)
    db_session.flush()
    return session.id


def add_event(
    db_session,
    external_id: str,
    occurred_at: datetime.datetime,
    hook: dict | None = None,
    session_id: int | None = None,
    job: bool = False,
    failed: bool = False,
) -> int:
    """A hook event as the hook client sends it: applied to session_id, or still queued."""
    hook = {"session_id": external_id, "hook_event_name": "PostToolUse", **(hook or {})}
    event = RecordedEvent(
        source=CLAUDE,
        delivery_id=f"delivery-{next(_delivery_ids)}",
        type=hook["hook_event_name"],
        occurred_at=occurred_at,
        payload={"hook": hook},
        processed_at=occurred_at if session_id else None,
        agent_session_id=session_id,
    )
    db_session.add(event)
    db_session.flush()
    if job:
        jobs = SqlJobQueue(db_session)
        jobs.enqueue(event.id, JobKind.APPLY_TO_SESSION)
        if failed:
            jobs.give_up(jobs.claim_next(), "boom")
    return event.id
