from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from flightlog.models import AgentSession, EventLog


def test_inserting_event_log_twice_throws_integrity_error(db_session: Session):
    event = EventLog(
        source="github",
        delivery_id="1234",
        type="pull_request",
        occurred_at=datetime.now(UTC),
        payload={
            "title": "title",
        },
    )

    db_session.add(event)
    db_session.commit()

    event2 = EventLog(
        source="github",
        delivery_id="1234",
        type="pull_request",
        occurred_at=datetime.now(UTC),
        payload={
            "title": "title",
        },
    )

    db_session.add(event2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_inserting_agent_session_twice_throws_integrity_error(db_session: Session):
    session = AgentSession(
        source="github",
        external_id="1234",
        repo="repo",
        branch="branch",
        started_at=datetime.now(UTC),
    )

    db_session.add(session)
    db_session.commit()

    session2 = AgentSession(
        source="github",
        external_id="1234",
        repo="repo",
        branch="branch",
        started_at=datetime.now(UTC),
    )

    db_session.add(session2)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()
