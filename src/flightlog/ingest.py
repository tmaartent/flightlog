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

    new_id = store_event_log(delivery_id, event_type, "github", payload)

    return {"status": "created" if new_id is not None else "duplicate"}, 202


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
    delivery_id: str, event_type: str, source: str, payload: dict[str, Any]
) -> int | None:
    occurred_at = extract_event_timestamp(event_type, payload)

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
