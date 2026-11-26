"""The read API: sessions as JSON, for scripts and agents, one Bearer key per connector.

Authenticated in before_request (ADR-0005), so a route added later can't forget it. No cookies
are read here, which is why there is no CSRF check: a browser can't attach a Bearer header
to a cross-site request by itself. Errors are JSON through api/errors.py.
"""

import datetime
from typing import Any

from flask import Blueprint, current_app, g, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import BadRequest, NotFound

from flightlog.api.session_filter import parse_session_filter
from flightlog.application.api_keys import authenticate
from flightlog.application.ports import AgentSessionQueries, UnitOfWork
from flightlog.application.timeline import session_timeline
from flightlog.contracts.sessions import LinkedPullRequest, SessionSummary
from flightlog.contracts.timeline import TimelineEntry

bp = Blueprint("read_api", __name__, url_prefix="/api/v1")

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
# One answer for every failure: a client (or attacker) can't tell a revoked key from a typo.
UNAUTHORIZED = {"error": "invalid or missing API key"}


@bp.before_request
def require_api_key() -> ResponseReturnValue | None:
    """Every route needs `Authorization: Bearer fl_…`. Sets g.connector for later layers."""
    credentials = request.authorization  # Werkzeug parses the header; None when absent
    connector = None
    if credentials is not None and credentials.type == "bearer" and credentials.token:
        uow: UnitOfWork = current_app.extensions["unit_of_work"]()
        connector = authenticate(credentials.token, uow)
    if connector is None:
        # RFC 6750: a 401 says which scheme to use. No error= detail, on purpose.
        return UNAUTHORIZED, 401, {"WWW-Authenticate": 'Bearer realm="flightlog"'}
    g.connector = connector
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
