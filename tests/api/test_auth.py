"""The admin login and CSRF tokens (ADR-0012), through Flask's test client."""

import datetime
from email.utils import parsedate_to_datetime

import pytest
from werkzeug.security import check_password_hash

from flightlog import create_app
from tests.harness import TEST_ADMIN_PASSWORD, make_app
from tests.util import csrf_token


def log_in(client, password: str = TEST_ADMIN_PASSWORD, next_url: str | None = None, **extra):
    data = {"password": password, "csrf_token": csrf_token(client), **extra}
    url = "/login" if next_url is None else f"/login?next={next_url}"
    return client.post(url, data=data)


def is_admin(client) -> bool:
    with client.session_transaction() as session:
        return session.get("admin") is True


@pytest.mark.db
@pytest.mark.parametrize("path", ["/sessions", "/sessions/1", "/admin/jobs"])
def test_a_page_without_login_redirects_to_the_login(client, path):
    response = client.get(path)

    assert response.status_code == 302
    assert response.headers["Location"] == f"/login?next={path}"


@pytest.mark.db
def test_the_redirect_keeps_the_query_string(client):
    response = client.get("/sessions?repo=api")

    assert response.headers["Location"] == "/login?next=/sessions?repo%3Dapi"


@pytest.mark.db
def test_machine_endpoints_need_no_login(client):
    assert client.get("/health").status_code == 200


@pytest.mark.db
def test_the_login_page_has_a_password_field_and_a_csrf_token(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert 'type="password"' in response.text
    assert f'name="csrf_token" value="{csrf_token(client)}"' in response.text


@pytest.mark.db
def test_the_right_password_logs_in(client):
    response = log_in(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/sessions"
    assert is_admin(client)
    assert client.get("/sessions").status_code == 200


@pytest.mark.db
def test_a_wrong_password_does_not(client):
    response = log_in(client, password="wrong")

    assert response.status_code == 401
    assert "Wrong password" in response.text
    assert not is_admin(client)


@pytest.mark.db
def test_login_without_a_csrf_token_is_refused(client):
    response = client.post("/login", data={"password": TEST_ADMIN_PASSWORD})

    assert response.status_code == 400
    assert not is_admin(client)


@pytest.mark.db
def test_login_with_a_wrong_csrf_token_is_refused(client):
    csrf_token(client)

    response = client.post("/login", data={"password": TEST_ADMIN_PASSWORD, "csrf_token": "forged"})

    assert response.status_code == 400


@pytest.mark.db
def test_login_goes_back_to_the_page_that_asked_for_it(client):
    response = log_in(client, next_url="/sessions/3")

    assert response.headers["Location"] == "/sessions/3"


@pytest.mark.db
@pytest.mark.parametrize(
    "next_url", ["//evil.example", "https://evil.example/", "/\\evil.example", "sessions", ""]
)
def test_login_never_redirects_off_site(client, next_url):
    response = log_in(client, next_url=next_url)

    assert response.headers["Location"] == "/sessions"


@pytest.mark.db
def test_login_starts_a_fresh_session(client):
    """Session fixation: nothing put in the session before login survives it."""
    with client.session_transaction() as session:
        session["planted"] = "by someone else"

    log_in(client)

    with client.session_transaction() as session:
        assert "planted" not in session


@pytest.mark.db
def test_the_session_cookie_is_http_only_and_same_site_lax(client):
    response = log_in(client)

    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


@pytest.mark.db
def test_the_login_lasts_twelve_hours(client):
    response = log_in(client)

    expires = response.headers["Set-Cookie"].split("Expires=")[1].split(";")[0]
    left = parsedate_to_datetime(expires) - datetime.datetime.now(datetime.UTC)
    assert datetime.timedelta(hours=11) < left <= datetime.timedelta(hours=12)


def test_the_session_cookie_is_secure_outside_debug_mode():
    app = create_app({"TESTING": True, "DATABASE_URL": "postgresql+psycopg://unused"})

    assert app.config["SESSION_COOKIE_SECURE"] is True


@pytest.mark.db
def test_logout_ends_the_session(admin_client):
    response = admin_client.post("/logout", data={"csrf_token": csrf_token(admin_client)})

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert not is_admin(admin_client)


@pytest.mark.db
def test_logout_needs_a_post_with_a_csrf_token(admin_client):
    assert admin_client.get("/logout").status_code == 405
    assert admin_client.post("/logout").status_code == 400
    assert is_admin(admin_client)


@pytest.mark.db
def test_without_a_configured_password_nobody_can_log_in(db_engine):
    client = make_app(ADMIN_PASSWORD_HASH=None).test_client()

    page = client.get("/login")
    response = log_in(client)

    assert "not configured" in page.text
    assert response.status_code == 401
    assert not is_admin(client)


@pytest.mark.db
def test_hash_password_prints_a_hash_of_the_password(runner):
    result = runner.invoke(args=["hash-password"], input="s3cret\ns3cret\n")

    assert result.exit_code == 0
    printed = result.output.strip().splitlines()[-1]
    assert printed.startswith("scrypt:")
    assert check_password_hash(printed, "s3cret")
