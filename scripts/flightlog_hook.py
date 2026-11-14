"""Claude Code hook client: sends every hook event, signed, to Flightlog.

Standard library only, because Claude Code runs it with the system Python, outside the
project's virtualenv. It must never get in the agent's way: whatever happens, it exits 0.

Environment: FLIGHTLOG_URL (e.g. http://localhost:5000) and CLAUDE_HOOK_SECRET.
"""

import datetime
import hashlib
import hmac
import json
import os
import sys
import urllib.request
import uuid

SIGNATURE_HEADER = "X-Flightlog-Signature"


def make_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_request(
    secret: str, now: datetime.datetime, delivery_id: str, hook: dict
) -> tuple[bytes, dict[str, str]]:
    """The signed body and headers for one hook event. Pure, so tests can check it exactly.

    delivery_id and occurred_at live inside the signed body: Claude Code sends neither, and
    putting them in the body means nobody can change them without breaking the signature.
    """
    payload = json.dumps(
        {
            "delivery_id": delivery_id,
            # isoformat keeps microseconds and the offset: tool calls often happen within
            # the same second, and the order between them matters (ADR-0004).
            "occurred_at": now.isoformat(),
            "hook": hook,
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: make_signature(payload, secret),
    }
    return payload, headers


def main() -> None:
    try:
        base_url = os.environ.get("FLIGHTLOG_URL")
        secret = os.environ.get("CLAUDE_HOOK_SECRET")
        if not base_url or not secret:
            print("FLIGHTLOG_URL or CLAUDE_HOOK_SECRET not set", file=sys.stderr)
            return
        # urlopen also opens file: and ftp: URLs; only ever talk HTTP to Flightlog.
        if not base_url.startswith(("http://", "https://")):
            print("FLIGHTLOG_URL must be an http(s) URL", file=sys.stderr)
            return

        # Bytes, so json detects UTF-8 itself instead of using the Windows console code page.
        hook = json.loads(sys.stdin.buffer.read())
        if not isinstance(hook, dict):
            print("Hook input is not a JSON object", file=sys.stderr)
            return

        payload, headers = build_request(
            secret, datetime.datetime.now(datetime.UTC), str(uuid.uuid4()), hook
        )
        url = f"{base_url.rstrip('/')}/ingest/claude"
        # S310: the scheme is checked above.
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")  # noqa: S310
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
            print(response.status, file=sys.stderr)
    except Exception as e:  # never fail the agent, whatever went wrong
        print(f"flightlog hook: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
    sys.exit(0)
