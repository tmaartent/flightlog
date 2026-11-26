from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest

from flightlog.contracts.sessions import SessionCursor, SessionFilter
from flightlog.domain import AgentSessionStatus

STATUSES = [status.value for status in AgentSessionStatus]


def parse_session_filter(args: MultiDict[str, str], limit: int) -> SessionFilter:
    """The query string as a SessionFilter. An empty field means "any"; a bad value is a 400.

    Shared by the dashboard and the read API (M4), so both accept exactly the same filters.
    """
    status = args.get("status") or None
    if status is not None and status not in STATUSES:
        raise BadRequest(f"status must be one of: {', '.join(STATUSES)}")

    after = args.get("after") or None
    try:
        cursor = SessionCursor.from_token(after) if after else None
    except ValueError:
        raise BadRequest("after is not a cursor from a previous page") from None

    return SessionFilter(
        repo=args.get("repo") or None,
        status=AgentSessionStatus(status) if status else None,
        after=cursor,
        limit=limit,
    )
