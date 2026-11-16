import datetime

from tests.util import make_signature

NOW = datetime.datetime(2026, 11, 14, 10, 15, 30, 123456, tzinfo=datetime.UTC)
HOOK = {
    "session_id": "session-1",
    "hook_event_name": "PostToolUse",
    "cwd": "/work/flightlog",
    "tool_name": "Bash",
    "tool_input": {"command": "pytest"},
}


def envelope(
    hook: object = HOOK, occurred_at: datetime.datetime | str | None = NOW, **overrides
) -> dict:
    """The hook client's envelope. hook and occurred_at may be invalid on purpose."""
    if isinstance(occurred_at, datetime.datetime):
        occurred_at = occurred_at.isoformat()
    return {
        "delivery_id": "delivery-001",
        "occurred_at": occurred_at,
        "hook": hook,
    } | overrides


def post_envelope(client, body: bytes, signature: str | None = None):
    secret = client.application.config["CLAUDE_HOOK_SECRET"]
    signature = make_signature(body, secret) if signature is None else signature
    return client.post(
        "/ingest/claude",
        data=body,
        content_type="application/json",
        headers={"X-Flightlog-Signature": signature},
    )
