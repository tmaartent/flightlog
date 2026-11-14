import datetime
import json

import pytest
from flightlog_hook import build_request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flightlog.models import EventLog
from tests.util import make_signature

NOW = datetime.datetime(2026, 11, 14, 10, 15, 30, 123456, tzinfo=datetime.UTC)
HOOK = {
    "session_id": "session-1",
    "hook_event_name": "PostToolUse",
    "cwd": "/work/flightlog",
    "tool_name": "Bash",
    "tool_input": {"command": "pytest"},
}


def envelope(**overrides) -> dict:
    return {"delivery_id": "delivery-001", "occurred_at": NOW.isoformat(), "hook": HOOK} | overrides


def post_envelope(client, body: bytes, signature: str | None = None):
    secret = client.application.config["CLAUDE_HOOK_SECRET"]
    signature = make_signature(body, secret) if signature is None else signature
    return client.post(
        "/ingest/claude",
        data=body,
        content_type="application/json",
        headers={"X-Flightlog-Signature": signature},
    )


def stored_events(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(EventLog))


@pytest.mark.db
def test_a_request_built_by_the_hook_client_is_accepted_and_stored(client, db_session):
    """Contract test: the client's format and the server's format must agree."""
    secret = client.application.config["CLAUDE_HOOK_SECRET"]
    body, headers = build_request(secret, NOW, "delivery-001", HOOK)

    response = client.post("/ingest/claude", data=body, headers=headers)

    assert response.status_code == 202
    assert response.get_json() == {"status": "created"}
    event = db_session.scalars(select(EventLog)).one()
    assert event.source == "claude"
    assert event.delivery_id == "delivery-001"
    assert event.type == "PostToolUse"
    assert event.occurred_at == NOW  # microseconds kept: ordering within a second
    assert event.payload["hook"] == HOOK


@pytest.mark.db
def test_the_same_delivery_twice_is_stored_once(client, db_session):
    body = json.dumps(envelope()).encode()

    post_envelope(client, body)
    second = post_envelope(client, body)

    assert second.status_code == 202
    assert second.get_json() == {"status": "duplicate"}
    assert stored_events(db_session) == 1


@pytest.mark.db
@pytest.mark.parametrize(
    ("signature", "case"),
    [
        (make_signature(b"other body", "test-claude-secret"), "signed for another body"),
        (make_signature(json.dumps(envelope()).encode(), "wrong-secret"), "wrong secret"),
        ("", "missing"),
    ],
)
def test_an_unverified_request_returns_401_and_is_not_stored(client, db_session, signature, case):
    response = post_envelope(client, json.dumps(envelope()).encode(), signature=signature)

    assert response.status_code == 401, case
    assert stored_events(db_session) == 0


@pytest.mark.db
@pytest.mark.parametrize(
    ("body", "case"),
    [
        (json.dumps(envelope(delivery_id=None)), "missing delivery_id"),
        (json.dumps(envelope(occurred_at=None)), "missing occurred_at"),
        (json.dumps(envelope(occurred_at="yesterday")), "unparseable occurred_at"),
        (json.dumps(envelope(occurred_at="2026-11-14T10:15:30")), "naive occurred_at"),
        (json.dumps(envelope(hook={"session_id": "s"})), "missing hook_event_name"),
        (json.dumps(envelope(hook="not an object")), "hook is not an object"),
        ("[1, 2]", "envelope is not an object"),
        ("not json", "invalid JSON"),
    ],
)
def test_a_malformed_request_returns_400_and_is_not_stored(client, db_session, body, case):
    response = post_envelope(client, body.encode())

    assert response.status_code == 400, case
    assert stored_events(db_session) == 0
