import datetime
import json

import pytest
from pytest import MonkeyPatch
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flightlog.ingest import extract_event_timestamp
from flightlog.models import EventLog
from tests.util import make_signature

PAYLOAD = {"action": "opened", "pull_request": {"updated_at": "2026-11-13T21:15:30Z"}}

# Placeholder meaning "compute the right signature for this body".
SIGNED = object()


def post_delivery(
    client,
    body: bytes | None = None,
    signature=SIGNED,
    event: str | None = "pull_request",
    delivery: str | None = "delivery-001",
):
    """POST to /ingest/github like GitHub does. Pass None to leave a header out."""
    body = json.dumps(PAYLOAD).encode() if body is None else body
    if signature is SIGNED:
        signature = make_signature(body, client.application.config["GITHUB_WEBHOOK_SECRET"])

    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
    }
    return client.post(
        "/ingest/github",
        data=body,
        content_type="application/json",
        headers={k: v for k, v in headers.items() if v is not None},
    )


def stored_events(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(EventLog))


@pytest.mark.db
def test_a_valid_delivery_is_stored_and_returns_202(client, db_session):
    response = post_delivery(client)

    assert response.status_code == 202
    assert response.get_json() == {"status": "created"}

    event = db_session.scalars(select(EventLog)).one()
    assert event.source == "github"
    assert event.delivery_id == "delivery-001"
    assert event.type == "pull_request"
    assert event.payload == PAYLOAD
    assert event.occurred_at == datetime.datetime(2026, 11, 13, 21, 15, 30, tzinfo=datetime.UTC)
    assert event.processed_at is None


@pytest.mark.db
def test_the_same_delivery_twice_is_stored_once(client, db_session):
    first = post_delivery(client)
    second = post_delivery(client)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.get_json() == {"status": "duplicate"}
    assert stored_events(db_session) == 1


@pytest.mark.db
def test_a_different_delivery_is_stored_separately(client, db_session):
    post_delivery(client, delivery="delivery-001")
    post_delivery(client, delivery="delivery-002")

    assert stored_events(db_session) == 2


@pytest.mark.db
@pytest.mark.parametrize(
    ("signature", "case"),
    [
        (make_signature(b"other body", "test-github-secret"), "signed for another body"),
        (make_signature(json.dumps(PAYLOAD).encode(), "wrong-secret"), "wrong secret"),
        (None, "missing"),
    ],
)
def test_an_unverified_delivery_returns_401_and_is_not_stored(client, db_session, signature, case):
    response = post_delivery(client, signature=signature)

    assert response.status_code == 401, case
    assert stored_events(db_session) == 0


@pytest.mark.db
@pytest.mark.parametrize(
    ("kwargs", "case"),
    [
        ({"delivery": None}, "missing X-GitHub-Delivery"),
        ({"event": None}, "missing X-GitHub-Event"),
        ({"body": b"not json"}, "invalid JSON"),
        ({"body": b"[1, 2]"}, "JSON array instead of an object"),
    ],
)
def test_a_malformed_delivery_returns_400_and_is_not_stored(client, db_session, kwargs, case):
    response = post_delivery(client, **kwargs)

    assert response.status_code == 400, case
    assert stored_events(db_session) == 0


def test_extract_event_timestamp_returns_correct_timestamp_for_pull_request():
    payload = {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "id": 100200300,
            "number": 42,
            "state": "open",
            "title": "Add webhook signature verification",
            "created_at": "2026-11-13T21:10:00Z",
            "updated_at": "2026-11-13T21:15:30Z",
            "closed_at": None,
            "head": {
                "ref": "feat/webhook-auth",
                "sha": "abc123def4567890",
            },
            "base": {
                "ref": "main",
                "sha": "0001112223334445",
            },
        },
        "repository": {
            "id": 555666777,
            "full_name": "owner/flightlog",
        },
        "sender": {
            "login": "octocat",
        },
    }

    dt = extract_event_timestamp("pull_request", payload)
    assert dt == datetime.datetime(2026, 11, 13, 21, 15, 30, tzinfo=datetime.UTC)


def test_extract_event_timestamp_returns_correct_timestamp_for_push():
    payload = {
        "ref": "refs/heads/main",
        "before": "0001112223334445",
        "after": "abc123def4567890",
        "head_commit": {
            "id": "abc123def4567890",
            "message": "Fix Alembic naming convention",
            "timestamp": "2026-11-13T22:18:00+01:00",
            "author": {
                "name": "Octocat",
                "email": "octocat@example.com",
            },
        },
        "repository": {
            "id": 555666777,
            "full_name": "owner/flightlog",
            "pushed_at": 1794604680,
        },
        "sender": {
            "login": "octocat",
        },
    }

    dt = extract_event_timestamp("push", payload)
    assert dt == datetime.datetime(
        2026, 11, 13, 22, 18, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1))
    )


def test_extract_event_timestamp_returns_correct_timestamp_for_workflow_run():
    payload = {
        "action": "completed",
        "workflow_run": {
            "id": 987654321,
            "name": "CI",
            "head_branch": "main",
            "head_sha": "abc123def4567890",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-11-13T21:20:00Z",
            "run_started_at": "2026-11-13T21:20:05Z",
            "updated_at": "2026-11-13T21:22:45Z",
        },
        "repository": {
            "id": 555666777,
            "full_name": "owner/flightlog",
        },
        "sender": {
            "login": "octocat",
        },
    }

    dt = extract_event_timestamp("workflow_run", payload)
    assert dt == datetime.datetime(2026, 11, 13, 21, 22, 45, tzinfo=datetime.UTC)


def test_extract_event_timestamp_returns_fallback_for_unknown_event_type(monkeypatch: MonkeyPatch):
    fixed_now = datetime.datetime(2026, 11, 13, 21, 15, 30, tzinfo=datetime.UTC)

    class MockDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz: datetime.tzinfo | None = None):
            return fixed_now

    monkeypatch.setattr(datetime, "datetime", MockDateTime)

    payload = {
        "action": "created",
        "zen": "Keep it logically awesome.",
        "repository": {
            "id": 555666777,
            "full_name": "owner/flightlog",
        },
        "sender": {
            "login": "octocat",
        },
    }

    dt = extract_event_timestamp("unknown", payload)
    assert dt == fixed_now


def test_extract_event_timestamp_falls_back_to_now_for_a_malformed_timestamp():
    before = datetime.datetime.now(datetime.UTC)

    dt = extract_event_timestamp("pull_request", {"pull_request": {"updated_at": "garbage"}})

    assert before <= dt <= datetime.datetime.now(datetime.UTC)
