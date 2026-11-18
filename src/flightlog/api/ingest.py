import datetime
from typing import Any

from flask import Blueprint, abort, current_app, request
from flask.typing import ResponseReturnValue

from flightlog.api.signatures import verify
from flightlog.application.ingest import ingest_event
from flightlog.application.ports import UnitOfWork
from flightlog.contracts.ingest import CLAUDE, GITHUB, IngestEvent, IngestResult

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

    payload = request.get_json()  # invalid JSON â†’ Flask answers 400 itself
    if not isinstance(payload, dict):
        abort(400, "Payload must be a JSON object")

    command = IngestEvent(
        source=GITHUB,
        delivery_id=delivery_id,
        type=event_type,
        occurred_at=extract_event_timestamp(event_type, payload),
        payload=payload,
    )
    return accepted(ingest_event(command, unit_of_work()))


@bp.route("/claude", methods=["POST"])
def claude() -> ResponseReturnValue:
    # Verify on the raw bytes, before anything parses the body.
    body = request.get_data()
    secret = current_app.config["CLAUDE_HOOK_SECRET"]
    if not verify(secret, body, request.headers.get("X-Flightlog-Signature")):
        abort(401, "Request could not be verified")

    # Everything below comes from the signed body (the envelope built by
    # scripts/flightlog_hook.py), never from unsigned headers.
    envelope = request.get_json()  # invalid JSON â†’ Flask answers 400 itself
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

    command = IngestEvent(
        source=CLAUDE,
        delivery_id=delivery_id,
        type=event_type,
        occurred_at=occurred_at,
        payload=envelope,
    )
    return accepted(ingest_event(command, unit_of_work()))


def unit_of_work() -> UnitOfWork:
    """The unit of work wired in by create_app (the API doesn't know which implementation)."""
    return current_app.extensions["unit_of_work"]()


def accepted(result: IngestResult) -> ResponseReturnValue:
    # 202 for a duplicate too: the sender did nothing wrong, it just delivered twice.
    return {"status": result.outcome.value}, 202


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
