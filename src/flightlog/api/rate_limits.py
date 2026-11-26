"""Rate limits with Flask-Limiter (ADR-0014). Only the read API and the login are limited.

The read API is keyed on the connector, so clients behind one IP don't share a budget, and a
request without a valid key is keyed on its IP with a lower limit, to slow down guessing.
/ingest, /health and the dashboard have no limits: there are no default limits at all.
"""

from flask import Flask, current_app, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from flightlog.api import auth, read_api

DEFAULTS = {
    # Every config key can be overridden from the environment (FLASK_RATELIMIT_…).
    "RATELIMIT_API": "120 per minute",
    "RATELIMIT_API_ANONYMOUS": "20 per minute",
    "RATELIMIT_LOGIN": "5 per minute; 20 per hour",
    # Per process: with several gunicorn workers each one counts on its own (ADR-0014).
    "RATELIMIT_STORAGE_URI": "memory://",
    # No burst of twice the limit across a window's edge, without a timestamp per hit.
    "RATELIMIT_STRATEGY": "sliding-window-counter",
    # X-RateLimit-* on limited routes, and Retry-After on a 429.
    "RATELIMIT_HEADERS_ENABLED": True,
}


def api_key() -> str:
    """The bucket for a read API request: its connector, or its IP when the key isn't valid."""
    connector = read_api.current_connector()
    return f"connector:{connector.id}" if connector else f"ip:{get_remote_address()}"


def api_limit() -> str:
    limit = "RATELIMIT_API" if read_api.current_connector() else "RATELIMIT_API_ANONYMOUS"
    return current_app.config[limit]


def login_limit() -> str:
    return current_app.config["RATELIMIT_LOGIN"]


def init_app(app: Flask) -> Limiter:
    """A Limiter per app, so every test app starts with empty counters."""
    for key, value in DEFAULTS.items():
        app.config.setdefault(key, value)  # after from_prefixed_env, so the environment wins

    limiter = Limiter(key_func=lambda: f"ip:{get_remote_address()}", app=app)
    # Shared: one bucket for every route of the blueprint, not one per endpoint.
    limiter.shared_limit(api_limit, scope="read_api", key_func=api_key)(read_api.bp)
    limiter.limit(
        login_limit,
        methods=["POST"],
        # Logout is a POST on the same blueprint too; only password guesses are limited.
        exempt_when=lambda: request.endpoint != "auth.login",
    )(auth.bp)
    return limiter
