"""The read API: sessions as JSON, for scripts and agents, one Bearer key per connector.

Authenticated in before_request (ADR-0005), so a route added later can't forget it. No cookies
are read here, which is why there is no CSRF check: a browser can't attach a Bearer header
to a cross-site request by itself. Errors are JSON through api/errors.py.
"""

import datetime
from typing import Any

from flask import Blueprint, current_app, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import BadRequest, NotFound

from flightlog.api.audit import audit_object
from flightlog.api.bearer import current_connector
from flightlog.api.session_filter import parse_session_filter
from flightlog.api.session_json import session_json
from flightlog.application.ports import AgentSessionQueries, DigestQueries
from flightlog.application.recent import session_summary, summary_page
from flightlog.application.timeline import session_timeline
from flightlog.contracts.digest import SummaryFilter
from flightlog.contracts.sessions import LinkedPullRequest, SessionCursor, SessionSummary
from flightlog.contracts.timeline import TimelineEntry

bp = Blueprint("read_api", __name__, url_prefix="/api/v1")

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
# One answer for every failure: a client (or attacker) can't tell a revoked key from a typo.
UNAUTHORIZED = {"error": "invalid or missing API key"}


@bp.before_request
def require_api_key() -> ResponseReturnValue | None:
    """Every route needs `Authorization: Bearer fl_…`; later layers read g.connector."""
    if current_connector() is None:
        # RFC 6750: a 401 says which scheme to use. No error= detail, on purpose.
        return UNAUTHORIZED, 401, {"WWW-Authenticate": 'Bearer realm="flightlog"'}
    return None


@bp.get("/sessions")
def sessions() -> ResponseReturnValue:
    session_filter = parse_session_filter(request.args, parse_limit(request.args.get("limit")))
    page = queries().list_sessions(session_filter)
    return {
        "sessions": [summary_json(s) for s in page.sessions],
        "next": page.next_cursor.to_token() if page.next_cursor else None,
    }


@bp.get("/sessions/<int:session_id>")
def session(session_id: int) -> ResponseReturnValue:
    audit_object("session", session_id)  # before the lookup, so a 404 names the id too
    found = session_timeline(session_id, queries())
    if found is None:
        raise NotFound(f"no session with id {session_id}")
    return {
        "session": summary_json(found.session),
        "pull_requests": [pull_request_json(pr) for pr in found.pull_requests],
        "files_touched": found.files_touched,
        "test_runs": found.test_runs,
        "entries": [entry_json(e) for e in found.entries],
    }


@bp.get("/summaries")
def summaries() -> ResponseReturnValue:
    """Stored session summaries of one repo, newest first, keyset-paged (ADR-0020)."""
    page = summary_page(parse_summary_filter(), digest_queries())
    return {
        "summaries": [session_json(s) for s in page.summaries],
        "next": page.next_cursor.to_token() if page.next_cursor else None,
    }


# endpoint= keeps the audit log readable; the function name only avoids the use case's name.
@bp.get("/sessions/<int:session_id>/summary", endpoint="session_summary")
def session_summary_route(session_id: int) -> ResponseReturnValue:
    audit_object("session", session_id)
    found = session_summary(session_id, digest_queries())
    if found is None:
        raise NotFound(f"no session with id {session_id}")
    return {"session": session_json(found)}


def parse_summary_filter() -> SummaryFilter:
    args = request.args
    repo = args.get("repo") or None
    if repo is None:
        raise BadRequest("repo is required")
    since = args.get("since") or None
    try:
        since_at = (
            datetime.datetime.combine(
                datetime.date.fromisoformat(since), datetime.time(), datetime.UTC
            )
            if since
            else None
        )
    except ValueError:
        raise BadRequest("since must be a date like 2026-11-01") from None
    after = args.get("after") or None
    try:
        cursor = SessionCursor.from_token(after) if after else None
    except ValueError:
        raise BadRequest("after is not a cursor from a previous page") from None
    return SummaryFilter(
        repo=repo,
        path=args.get("path") or None,
        since=since_at,
        after=cursor,
        limit=parse_limit(args.get("limit")),
    )


def digest_queries() -> DigestQueries:
    return current_app.extensions["digest_queries"]()


def queries() -> AgentSessionQueries:
    return current_app.extensions["agent_session_queries"]()


def parse_limit(value: str | None) -> int:
    if not value:
        return DEFAULT_LIMIT
    if not value.isdigit() or not 1 <= int(value) <= MAX_LIMIT:
        raise BadRequest(f"limit must be a whole number from 1 to {MAX_LIMIT}")
    return int(value)


# Written out by hand: the JSON is a public contract, so a renamed dataclass field must not
# change it silently. Times are ISO 8601 in UTC; Flask's own JSON provider would write a
# datetime as an HTTP date ("Mon, 16 Nov 2026 10:00:00 GMT").


def iso(moment: datetime.datetime | None) -> str | None:
    return moment.astimezone(datetime.UTC).isoformat() if moment else None


def summary_json(s: SessionSummary) -> dict[str, Any]:
    return {
        "id": s.id,
        "source": s.source,
        "external_id": s.external_id,
        "repo": s.repo,
        "branch": s.branch,
        "status": s.status.value,
        "started_at": iso(s.started_at),
        "ended_at": iso(s.ended_at),
        "pending_events": s.pending_events,
    }


def pull_request_json(pr: LinkedPullRequest) -> dict[str, Any]:
    return {"number": pr.number, "title": pr.title, "outcome": pr.outcome.value}


def entry_json(e: TimelineEntry) -> dict[str, Any]:
    return {
        "occurred_at": iso(e.occurred_at),
        "kind": e.kind.value,
        "type": e.type,
        "tool_name": e.tool_name,
        "file_path": e.file_path,
        "command": e.command,  # masked by session_timeline, as on the dashboard
    }
