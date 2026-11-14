import datetime
from typing import Any

from flask import Blueprint, abort, current_app, request
from flask.typing import ResponseReturnValue
from sqlalchemy.dialects.postgresql import insert

from flightlog.db import get_session
from flightlog.models import EventLog
from flightlog.signatures import verify

bp = Blueprint("ingest", __name__, url_prefix="/ingest")


@bp.route("/github", methods=["POST"])
def github() -> ResponseReturnValue:
    # Verify on the raw bytes, before anything parses the body.
    body = request.get_data()
    secret = current_app.config["GITHUB_WEBHOOK_SECRET"]
    if not verify(secret, body, request.headers.get("X-Hub-Signature-256")):
        abort(401, "Request could not be verified")

    # Cheap header checks first, then parse.
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if not delivery_id:
        abort(400, "X-GitHub-Delivery header is required")
    event_type = request.headers.get("X-GitHub-Event")
    if not event_type:
        abort(400, "X-GitHub-Event header is required")

    payload = request.get_json()  # invalid JSON → Flask answers 400 itself
    if not isinstance(payload, dict):
        abort(400, "Payload must be a JSON object")

    occurred_at = extract_event_timestamp(event_type, payload)
    new_id = store_event_log(delivery_id, event_type, "github", payload, occurred_at)

    return {"status": "created" if new_id is not None else "duplicate"}, 202


@bp.route("/claude", methods=["POST"])
def claude() -> ResponseReturnValue:
    # Verify on the raw bytes, before anything parses the body.
    body = request.get_data()
    secret = current_app.config["CLAUDE_HOOK_SECRET"]
    if not verify(secret, body, request.headers.get("X-Flightlog-Signature")):
        abort(401, "Request could not be verified")

    # Everything below comes from the signed body (the envelope built by
    # scripts/flightlog_hook.py), never from unsigned headers.
    envelope = request.get_json()  # invalid JSON → Flask answers 400 itself
    if not isinstance(envelope, dict):
        abort(400, "Payload must be a JSON object")

    delivery_id = envelope.get("delivery_id")
    if not isinstance(delivery_id, str) or not delivery_id:
        abort(400, "delivery_id is required")

    occurred_at = parse_aware_datetime(envelope.get("occurred_at"))
    if occurred_at is None:
        abort(400, "occurred_at must be an ISO 8601 timestamp with a UTC offset")

    hook = envelope.get("hook")
    event_type = hook.get("hook_event_name") if isinstance(hook, dict) else None
    if not isinstance(event_type, str) or not event_type:
        abort(400, "hook.hook_event_name is required")

    new_id = store_event_log(delivery_id, event_type, "claude", envelope, occurred_at)

    return {"status": "created" if new_id is not None else "duplicate"}, 202


def parse_aware_datetime(value: Any) -> datetime.datetime | None:
    """An ISO 8601 timestamp with an offset, or None.

    A naive timestamp is rejected: it would be read as UTC and could be hours off,
    which breaks the ordering of a session's events.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def extract_event_timestamp(event_type: str, payload: dict[str, Any]) -> datetime.datetime:
    raw_ts: str | None = None

    if event_type == "workflow_run" and "workflow_run" in payload:
        raw_ts = payload["workflow_run"].get("updated_at") or payload["workflow_run"].get(
            "created_at"
        )
    elif event_type == "pull_request" and "pull_request" in payload:
        raw_ts = payload["pull_request"].get("updated_at") or payload["pull_request"].get(
            "created_at"
        )
    elif event_type == "push" and payload.get("head_commit"):
        raw_ts = payload["head_commit"].get("timestamp")

    if raw_ts:
        try:
            return datetime.datetime.fromisoformat(raw_ts)
        except ValueError:
            pass

    # Fallback to current UTC time if no timestamp field is present
    return datetime.datetime.now(datetime.UTC)


def store_event_log(
    delivery_id: str,
    event_type: str,
    source: str,
    payload: dict[str, Any],
    occurred_at: datetime.datetime,
) -> int | None:
    """Store an event once per (source, delivery_id). Returns the new id, or None if duplicate."""
    statement = (
        insert(EventLog)
        .values(
            delivery_id=delivery_id,
            source=source,
            payload=payload,
            type=event_type,
            occurred_at=occurred_at,
        )
        .on_conflict_do_nothing(index_elements=["delivery_id", "source"])
        .returning(EventLog.id)
    )

    session = get_session()
    new_id = session.scalar(statement)

    session.commit()
    return new_id
