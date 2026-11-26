"""The audit log's HTTP side (ADR-0015): one row per API call and per admin action.

An app-level after_request sees the final status of every response, including a 401 that a
before_request returned, an error handler's page and a 429 from the rate limiter.
"""

from flask import Flask, Response, current_app, g, request, session
from flask_limiter.util import get_remote_address

from flightlog.api.auth import UNSAFE_METHODS
from flightlog.api.bearer import current_connector
from flightlog.application.ports import AuditLog
from flightlog.contracts.audit import ActorKind, AuditEntry

# Admin actions are the unsafe methods on the cookie-authenticated blueprints.
ADMIN_BLUEPRINTS = frozenset({"auth", "admin", "dashboard"})
API_PREFIX = "/api/"


def audit_object(object_type: str, object_id: int | str) -> None:
    """Called by a view: which object the request is about, for its audit row."""
    g.audit_object = (object_type, str(object_id))


def is_audited() -> bool:
    if request.path.startswith(API_PREFIX):
        return True  # by path, so a URL that matches no route is recorded too
    return request.blueprint in ADMIN_BLUEPRINTS and request.method in UNSAFE_METHODS


def remember_admin() -> None:
    """before_request: logout clears the session, so who it was is known only beforehand."""
    g.audit_was_admin = session.get("admin") is True


def actor() -> tuple[ActorKind, int | None]:
    if request.path.startswith(API_PREFIX):
        connector = current_connector()  # cached on g; looked up here if no one did
        return (ActorKind.CONNECTOR, connector.id) if connector else (ActorKind.ANONYMOUS, None)
    if g.get("audit_was_admin") or session.get("admin") is True:
        return ActorKind.ADMIN, None  # was (logout) or is now (login)
    return ActorKind.ANONYMOUS, None


def write_audit_row(response: Response) -> Response:
    """after_request. Fail-open: if the row can't be written, log it and answer anyway."""
    if not is_audited():
        return response
    try:
        actor_kind, connector_id = actor()
        object_type, object_id = g.get("audit_object", (None, None))
        entry = AuditEntry(
            actor_kind=actor_kind,
            connector_id=connector_id,
            ip=get_remote_address(),
            method=request.method,
            endpoint=request.endpoint,
            path=request.path,
            object_type=object_type,
            object_id=object_id,
            status=response.status_code,
        )
        # The response is built, so the request's own session is done. Closing it first means
        # one pooled connection per request, not two at once, and the audit row's transaction
        # never sits inside the request's (in tests both share one connection).
        current_app.extensions["end_request_session"]()
        audit_log: AuditLog = current_app.extensions["audit_log"]()
        audit_log.record(entry)
    except Exception:
        current_app.logger.exception(
            "could not write the audit row for %s %s", request.method, request.path
        )
    return response


def init_app(app: Flask) -> None:
    app.before_request(remember_admin)
    app.after_request(write_audit_row)
