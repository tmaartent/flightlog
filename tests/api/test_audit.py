"""The audit log (ADR-0015): one row per API call and per admin action, nothing else."""

import datetime
import logging

import pytest
from sqlalchemy import select

from flightlog.application.api_keys import issue_key
from flightlog.contracts.audit import ActorKind
from flightlog.infrastructure.tables import audit_log, connectors
from flightlog.infrastructure.unit_of_work import SqlUnitOfWork
from tests.api.test_admin import failed_job, retry
from tests.harness import TEST_ADMIN_PASSWORD, make_test_app
from tests.session_util import add_started_session
from tests.util import csrf_token

NOW = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)


def rows(db_session):
    return db_session.execute(select(audit_log).order_by(audit_log.c.id)).all()


def new_connector(db_session, name: str = "ci-script") -> tuple[int, dict[str, str]]:
    uow = SqlUnitOfWork(db_session)
    key = issue_key(name, uow, NOW).key
    return uow.connectors.get_by_name(name).id, {"Authorization": f"Bearer {key}"}


# --- the read API ---------------------------------------------------------------------------


@pytest.mark.db
def test_every_api_call_leaves_one_row(client, db_session):
    connector_id, headers = new_connector(db_session)
    session_id = add_started_session(db_session, "s-1")

    client.get("/api/v1/sessions?repo=flightlog", headers=headers)
    client.get(f"/api/v1/sessions/{session_id}", headers=headers)

    first, second = rows(db_session)
    assert first.actor_kind is ActorKind.CONNECTOR
    assert first.connector_id == connector_id
    assert (first.method, first.endpoint, first.path) == (
        "GET",
        "read_api.sessions",
        "/api/v1/sessions",
    )
    assert (first.object_type, first.object_id, first.status) == (None, None, 200)
    assert first.ip == "127.0.0.1"
    assert (second.endpoint, second.object_type, second.object_id) == (
        "read_api.session",
        "session",
        str(session_id),
    )


@pytest.mark.db
def test_a_missing_session_is_still_recorded_with_its_id(client, db_session):
    _, headers = new_connector(db_session)

    client.get("/api/v1/sessions/999999", headers=headers)

    (row,) = rows(db_session)
    assert (row.object_type, row.object_id, row.status) == ("session", "999999", 404)


@pytest.mark.db
def test_a_refused_key_is_recorded_as_anonymous(client, db_session):
    client.get("/api/v1/sessions", headers={"Authorization": "Bearer fl_0a1b2c3d_wrong"})

    (row,) = rows(db_session)
    assert row.actor_kind is ActorKind.ANONYMOUS
    assert row.connector_id is None
    assert row.status == 401


@pytest.mark.db
def test_an_unknown_api_url_is_recorded_too(client, db_session):
    _, headers = new_connector(db_session)

    client.get("/api/v1/nope", headers=headers)

    (row,) = rows(db_session)
    assert (row.endpoint, row.path, row.status) == (None, "/api/v1/nope", 404)
    assert row.actor_kind is ActorKind.CONNECTOR


@pytest.mark.db
def test_a_rate_limited_call_is_recorded(db_connection, db_session):
    client = make_test_app(db_connection, RATELIMIT_API="1 per minute").test_client()
    _, headers = new_connector(db_session)

    client.get("/api/v1/sessions", headers=headers)
    client.get("/api/v1/sessions", headers=headers)

    assert [r.status for r in rows(db_session)] == [200, 429]


# --- admin actions --------------------------------------------------------------------------


def post_login(client, password: str):
    return client.post("/login", data={"password": password, "csrf_token": csrf_token(client)})


@pytest.mark.db
def test_login_and_logout_are_recorded(client, db_session):
    post_login(client, "not the password")
    post_login(client, TEST_ADMIN_PASSWORD)
    client.post("/logout", data={"csrf_token": csrf_token(client)})

    assert [(r.endpoint, r.actor_kind, r.status) for r in rows(db_session)] == [
        ("auth.login", ActorKind.ANONYMOUS, 401),
        ("auth.login", ActorKind.ADMIN, 302),  # admin once the login succeeded
        ("auth.logout", ActorKind.ADMIN, 302),  # admin until the logout cleared the session
    ]


@pytest.mark.db
def test_a_retry_is_recorded_with_its_job(admin_client, db_session):
    job_id = failed_job(db_session)

    retry(admin_client, job_id)

    (row,) = rows(db_session)
    assert (row.endpoint, row.actor_kind, row.method) == ("admin.retry", ActorKind.ADMIN, "POST")
    assert (row.object_type, row.object_id, row.status) == ("job", str(job_id), 302)


@pytest.mark.db
def test_a_forged_csrf_token_is_recorded(admin_client, db_session):
    job_id = failed_job(db_session)

    retry(admin_client, job_id, token="forged")

    (row,) = rows(db_session)
    assert row.status == 400


@pytest.mark.db
def test_an_admin_action_without_login_is_refused_and_recorded(client, db_session):
    """A 401, not a redirect to the login page: the redirect would drop the POST anyway."""
    job_id = failed_job(db_session)

    response = retry(client, job_id)

    assert response.status_code == 401
    (row,) = rows(db_session)
    assert (row.actor_kind, row.status) == (ActorKind.ANONYMOUS, 401)


@pytest.mark.db
def test_pages_webhooks_and_health_are_not_recorded(admin_client, client, db_session):
    for path in ["/sessions", "/admin/jobs", "/admin/connectors", "/admin/audit", "/login"]:
        admin_client.get(path)
    client.get("/health")
    client.post("/ingest/github", data=b"{}")

    assert rows(db_session) == []


# --- revoking from the admin page -----------------------------------------------------------


def revoke(client, connector_id: int, token: str | None = None):
    data = {"csrf_token": csrf_token(client) if token is None else token}
    return client.post(f"/admin/connectors/{connector_id}/revoke", data=data)


@pytest.mark.db
def test_the_revoke_button_revokes_and_is_recorded(admin_client, db_session):
    connector_id, headers = new_connector(db_session)
    page = admin_client.get("/admin/connectors").text
    assert f'action="/admin/connectors/{connector_id}/revoke"' in page

    response = revoke(admin_client, connector_id)

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/connectors"
    revoked_at = db_session.scalar(
        select(connectors.c.revoked_at).where(connectors.c.id == connector_id)
    )
    assert revoked_at is not None
    assert "Revoked connector" in admin_client.get("/admin/connectors").text
    (row,) = [r for r in rows(db_session) if r.endpoint == "admin.revoke_connector"]
    assert (row.object_type, row.object_id, row.status) == ("connector", str(connector_id), 302)


@pytest.mark.db
def test_revoking_twice_or_an_unknown_connector_says_so(admin_client, db_session):
    connector_id, _ = new_connector(db_session)
    revoke(admin_client, connector_id)

    revoke(admin_client, connector_id)
    assert "was already revoked" in admin_client.get("/admin/connectors").text
    revoke(admin_client, 999999)
    assert "No connector with id 999999" in admin_client.get("/admin/connectors").text


@pytest.mark.db
def test_revoking_needs_the_csrf_token(admin_client, db_session):
    connector_id, _ = new_connector(db_session)

    assert revoke(admin_client, connector_id, token="forged").status_code == 400


@pytest.mark.db
def test_a_revoked_connector_has_no_button(admin_client, db_session):
    connector_id, _ = new_connector(db_session)
    revoke(admin_client, connector_id)

    assert (
        f"/admin/connectors/{connector_id}/revoke" not in admin_client.get("/admin/connectors").text
    )


# --- the audit page -------------------------------------------------------------------------


@pytest.mark.db
def test_the_audit_page_lists_entries_with_filters(admin_client, client, db_session):
    _, headers = new_connector(db_session)
    client.get("/api/v1/sessions", headers=headers)
    client.get("/api/v1/sessions", headers={"Authorization": "Bearer fl_0a1b2c3d_wrong"})

    everything = admin_client.get("/admin/audit")
    denied = admin_client.get("/admin/audit?outcome=denied")
    by_connector = admin_client.get("/admin/audit?connector=ci-script")

    assert everything.status_code == 200
    assert everything.text.count("/api/v1/sessions") >= 2
    assert "ci-script" in by_connector.text
    assert "denied" in denied.text
    assert "ci-script" not in denied.text.split("<tbody>")[1]


@pytest.mark.db
@pytest.mark.parametrize("query", ["outcome=fine", "before=abc", "before=0"])
def test_the_audit_page_refuses_bad_filters(admin_client, query):
    assert admin_client.get(f"/admin/audit?{query}").status_code == 400


@pytest.mark.db
def test_the_audit_page_needs_the_login(client):
    assert client.get("/admin/audit").status_code == 302


# --- failing open ---------------------------------------------------------------------------


@pytest.mark.db
def test_a_broken_audit_log_does_not_break_the_response(app, db_session, caplog):
    """Fail-open (ADR-0015): the error is logged and the caller still gets its answer."""

    class BrokenAuditLog:
        def record(self, entry):
            raise RuntimeError("audit database is down")

    app.extensions["audit_log"] = BrokenAuditLog
    _, headers = new_connector(db_session)

    with caplog.at_level(logging.ERROR):
        response = app.test_client().get("/api/v1/sessions", headers=headers)

    assert response.status_code == 200
    assert "audit database is down" in caplog.text
    assert "could not write the audit row" in caplog.text
