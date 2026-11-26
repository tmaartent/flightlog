"""ProxyFix only when a proxy is configured (ADR-0017): X-Forwarded-For is otherwise a lie."""

import pytest
from werkzeug.middleware.proxy_fix import ProxyFix

from flightlog import create_app
from tests.harness import make_test_app

FORWARDED = {"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"}


def test_without_a_proxy_the_forwarded_headers_are_ignored():
    app = create_app({"TESTING": True, "DATABASE_URL": "postgresql+psycopg://x@localhost/x"})

    assert not isinstance(app.wsgi_app, ProxyFix)


@pytest.mark.db
def test_a_client_can_not_pick_its_own_ip_without_a_proxy(db_connection, db_session):
    """Otherwise every request could claim a new IP and dodge the per-IP limits."""
    client = make_test_app(db_connection, RATELIMIT_API_ANONYMOUS="1 per minute").test_client()

    first = client.get("/api/v1/sessions", headers={"X-Forwarded-For": "203.0.113.1"})
    second = client.get("/api/v1/sessions", headers={"X-Forwarded-For": "203.0.113.2"})

    assert (first.status_code, second.status_code) == (401, 429)


@pytest.mark.db
def test_behind_one_proxy_the_client_ip_comes_from_the_header(db_connection, db_session):
    client = make_test_app(
        db_connection, PROXY_COUNT=1, RATELIMIT_API_ANONYMOUS="1 per minute"
    ).test_client()

    first = client.get("/api/v1/sessions", headers={"X-Forwarded-For": "203.0.113.1"})
    other_client = client.get("/api/v1/sessions", headers={"X-Forwarded-For": "203.0.113.2"})
    same_again = client.get("/api/v1/sessions", headers={"X-Forwarded-For": "203.0.113.1"})

    assert (first.status_code, other_client.status_code, same_again.status_code) == (401, 401, 429)


def test_the_proxy_count_is_used_for_for_and_proto():
    app = create_app(
        {"TESTING": True, "DATABASE_URL": "postgresql+psycopg://x@localhost/x", "PROXY_COUNT": 2}
    )

    assert isinstance(app.wsgi_app, ProxyFix)
    assert (app.wsgi_app.x_for, app.wsgi_app.x_proto, app.wsgi_app.x_host) == (2, 2, 0)
