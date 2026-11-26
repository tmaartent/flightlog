"""Rate limits (ADR-0014): per connector on the read API, per IP without a key and on login."""

import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from flightlog.application.api_keys import issue_key, revoke_key
from flightlog.infrastructure.unit_of_work import SqlUnitOfWork
from tests.harness import TEST_ADMIN_PASSWORD, make_app
from tests.util import csrf_token

NOW = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)


@pytest.fixture
def client(db_connection):
    """Low limits, so a test reaches them in a few requests. A fresh app has fresh counters."""
    app = make_app(
        RATELIMIT_API="3 per minute",
        RATELIMIT_API_ANONYMOUS="2 per minute",
        RATELIMIT_LOGIN="2 per minute",
    )
    app.extensions["sessionmaker"] = sessionmaker(
        bind=db_connection, join_transaction_mode="create_savepoint"
    )
    return app.test_client()


def bearer(db_session, name: str = "ci-script") -> dict[str, str]:
    key = issue_key(name, SqlUnitOfWork(db_session), NOW).key
    return {"Authorization": f"Bearer {key}"}


def get_sessions(client, headers=None, times: int = 1):
    return [client.get("/api/v1/sessions", headers=headers) for _ in range(times)][-1]


# --- per connector --------------------------------------------------------------------------


@pytest.mark.db
def test_a_connector_over_its_limit_gets_a_json_429_with_retry_after(client, db_session):
    headers = bearer(db_session)
    assert get_sessions(client, headers, times=3).status_code == 200

    response = client.get("/api/v1/sessions", headers=headers)

    assert response.status_code == 429
    assert response.json == {"error": "rate limit exceeded: 3 per 1 minute"}
    assert 0 < int(response.headers["Retry-After"]) <= 60


@pytest.mark.db
def test_responses_say_how_much_of_the_limit_is_left(client, db_session):
    response = get_sessions(client, bearer(db_session))

    assert response.headers["X-RateLimit-Limit"] == "3"
    assert response.headers["X-RateLimit-Remaining"] == "2"


@pytest.mark.db
def test_one_limit_covers_every_api_route(client, db_session):
    headers = bearer(db_session)
    get_sessions(client, headers, times=2)
    client.get("/api/v1/sessions/999999", headers=headers)  # a 404 counts too

    assert get_sessions(client, headers).status_code == 429


@pytest.mark.db
def test_each_connector_has_its_own_budget(client, db_session):
    """Keyed on the connector, not the IP: both connectors share 127.0.0.1 here."""
    first, second = bearer(db_session, "one"), bearer(db_session, "two")
    assert get_sessions(client, first, times=4).status_code == 429

    assert get_sessions(client, second).status_code == 200


# --- without a valid key --------------------------------------------------------------------


@pytest.mark.db
def test_requests_without_a_valid_key_are_limited_per_ip(client):
    wrong = {"Authorization": "Bearer fl_0a1b2c3d_wrong"}
    assert get_sessions(client, wrong, times=2).status_code == 401

    response = get_sessions(client)  # no key at all: the same IP bucket

    assert response.status_code == 429
    assert "Retry-After" in response.headers


@pytest.mark.db
def test_guessing_keys_does_not_use_up_a_connectors_budget(client, db_session):
    get_sessions(client, {"Authorization": "Bearer fl_0a1b2c3d_wrong"}, times=3)

    assert get_sessions(client, bearer(db_session)).status_code == 200


@pytest.mark.db
def test_a_revoked_key_counts_as_no_key(client, db_session):
    headers = bearer(db_session)
    revoke_key("ci-script", SqlUnitOfWork(db_session), NOW)

    assert get_sessions(client, headers, times=2).status_code == 401
    assert get_sessions(client, headers).status_code == 429


# --- login ----------------------------------------------------------------------------------


WRONG_PASSWORD = "wrong"


def post_login(client, password: str = WRONG_PASSWORD):
    return client.post("/login", data={"password": password, "csrf_token": csrf_token(client)})


@pytest.mark.db
def test_login_attempts_are_limited_per_ip(client):
    assert post_login(client).status_code == 401
    assert post_login(client).status_code == 401

    response = post_login(client, TEST_ADMIN_PASSWORD)  # even the right password waits

    assert response.status_code == 429
    assert "Retry-After" in response.headers


@pytest.mark.db
def test_showing_the_login_page_is_not_limited(client):
    for _ in range(5):
        assert client.get("/login").status_code == 200


# --- no limits elsewhere --------------------------------------------------------------------


@pytest.mark.db
def test_webhooks_and_health_are_not_limited(client):
    """GitHub doesn't retry a 429 well, and the signature check already refuses strangers."""
    for _ in range(5):
        assert client.post("/ingest/github", data=b"{}").status_code == 401
        response = client.get("/health")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers
