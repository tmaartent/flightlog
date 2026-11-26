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
import shutil
import subprocess
import sys
import urllib.request
import uuid

SIGNATURE_HEADER = "X-Flightlog-Signature"
# Calls to Flightlog's own MCP tools are not sent: Flightlog would log itself (ADR-0019).
OWN_MCP_TOOLS = "mcp__flightlog__"


def make_signature(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def current_branch(cwd: str | os.PathLike[str]) -> str | None:
    """The branch checked out in cwd, or None: no git, not a repo, detached HEAD, or too slow.

    Never raises, and gives up after a second: the hook must not slow the agent down.
    """
    git = shutil.which("git")
    if not git or not str(cwd).strip() or not os.path.isdir(cwd):
        return None
    try:
        result = subprocess.run(
            [git, "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    branch = result.stdout.strip()
    # A detached HEAD prints "HEAD": there is no branch to link a pull request to.
    if result.returncode != 0 or branch in ("", "HEAD"):
        return None
    return branch


def build_request(
    secret: str,
    now: datetime.datetime,
    delivery_id: str,
    hook: dict,
    branch: str | None = None,
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
            # Not part of Claude Code's hook input: added here, so a session can be linked to
            # the pull request opened from its branch (ADR-0009).
            "git": {"branch": branch},
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

        tool_name = hook.get("tool_name")
        if isinstance(tool_name, str) and tool_name.startswith(OWN_MCP_TOOLS):
            return

        cwd = hook.get("cwd")
        branch = current_branch(cwd) if isinstance(cwd, str) else None
        payload, headers = build_request(
            secret, datetime.datetime.now(datetime.UTC), str(uuid.uuid4()), hook, branch
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
