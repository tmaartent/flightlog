"""Who sent this request's Bearer key (ADR-0005). Shared by the read API, the rate limiter
(ADR-0014) and the audit log (ADR-0015), so it lives apart from all three.
"""

from flask import current_app, g, request

from flightlog.application.api_keys import authenticate
from flightlog.application.ports import UnitOfWork
from flightlog.contracts.connectors import ConnectorRef


def current_connector() -> ConnectorRef | None:
    """The connector this request's Bearer key belongs to, or None. Looked up once per request.

    Lazy on purpose (ADR-0014): Flask-Limiter checks limits in an app-level before_request,
    which runs before the read API's require_api_key. Whoever asks first does the lookup, so
    the order of the hooks doesn't matter.
    """
    if "connector" not in g:
        credentials = request.authorization  # Werkzeug parses the header; None when absent
        connector = None
        if credentials is not None and credentials.type == "bearer" and credentials.token:
            uow: UnitOfWork = current_app.extensions["unit_of_work"]()
            connector = authenticate(credentials.token, uow)
        g.connector = connector
    return g.connector
