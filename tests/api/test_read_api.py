"""The read API: GET /api/v1/sessions[/<id>] behind a Bearer key per connector (ADR-0005)."""

import datetime

import pytest

from flightlog.application.api_keys import issue_key, revoke_key
from flightlog.domain import AgentSessionStatus
from flightlog.infrastructure.unit_of_work import SqlUnitOfWork
from tests.session_util import add_event, add_started_session, at

NOW = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)
UNAUTHORIZED = {"error": "invalid or missing API key"}


def new_key(db_session, name: str = "ci-script") -> str:
    return issue_key(name, SqlUnitOfWork(db_session), NOW).key


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def assert_unauthorized(response) -> None:
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="flightlog"'
    assert response.json == UNAUTHORIZED


# --- authentication -------------------------------------------------------------------------


@pytest.mark.db
@pytest.mark.parametrize("path", ["/api/v1/sessions", "/api/v1/sessions/1"])
def test_no_key_is_refused(client, path):
    assert_unauthorized(client.get(path))


@pytest.mark.db
@pytest.mark.parametrize(
    "header",
    [
        "Bearer",
        "Bearer ",
        "Basic Y2ktc2NyaXB0OnNlY3JldA==",
        "fl_0a1b2c3d_not-a-bearer-header",
        "Bearer fl_0a1b2c3d_unknown-prefix",
    ],
)
def test_a_malformed_or_unknown_key_is_refused(client, header):
    assert_unauthorized(client.get("/api/v1/sessions", headers={"Authorization": header}))


@pytest.mark.db
def test_a_wrong_secret_is_refused(client, db_session):
    key = new_key(db_session)
    wrong = key[: -len("tail")] + "tail"

    assert_unauthorized(client.get("/api/v1/sessions", headers=bearer(wrong)))


@pytest.mark.db
def test_a_revoked_key_is_refused(client, db_session):
    key = new_key(db_session)
    assert client.get("/api/v1/sessions", headers=bearer(key)).status_code == 200

    revoke_key("ci-script", SqlUnitOfWork(db_session), NOW)

    assert_unauthorized(client.get("/api/v1/sessions", headers=bearer(key)))


@pytest.mark.db
def test_the_admin_cookie_is_not_an_api_key(admin_client):
    """The API has no cookies and so no CSRF: a logged-in browser gets nothing from it."""
    assert_unauthorized(admin_client.get("/api/v1/sessions"))


@pytest.mark.db
def test_each_connector_has_its_own_key(client, db_session):
    first, second = new_key(db_session, "one"), new_key(db_session, "two")
    revoke_key("one", SqlUnitOfWork(db_session), NOW)

    assert_unauthorized(client.get("/api/v1/sessions", headers=bearer(first)))
    assert client.get("/api/v1/sessions", headers=bearer(second)).status_code == 200


# --- GET /api/v1/sessions -------------------------------------------------------------------


@pytest.mark.db
def test_sessions_are_listed_newest_first_as_json(client, db_session):
    older = add_started_session(db_session, "s-old", started_at=at(0), branch="feat/x")
    newer = add_started_session(
        db_session, "s-new", started_at=at(10), status=AgentSessionStatus.STOPPED
    )

    response = client.get("/api/v1/sessions", headers=bearer(new_key(db_session)))

    assert response.status_code == 200
    assert response.json == {
        "sessions": [
            {
                "id": newer,
                "source": "claude",
                "external_id": "s-new",
                "repo": "flightlog",
                "branch": None,
                "status": "stopped",
                "started_at": "2026-11-16T10:10:00+00:00",
                "ended_at": None,
                "pending_events": 0,
            },
            {
                "id": older,
                "source": "claude",
                "external_id": "s-old",
                "repo": "flightlog",
                "branch": "feat/x",
                "status": "active",
                "started_at": "2026-11-16T10:00:00+00:00",
                "ended_at": None,
                "pending_events": 0,
            },
        ],
        "next": None,
    }


@pytest.mark.db
def test_sessions_are_filtered_by_repo_and_status(client, db_session):
    add_started_session(db_session, "a", repo="flightlog")
    add_started_session(db_session, "b", repo="other")
    add_started_session(db_session, "c", repo="other", status=AgentSessionStatus.STOPPED)
    headers = bearer(new_key(db_session))

    response = client.get("/api/v1/sessions?repo=other&status=active", headers=headers)

    assert [s["external_id"] for s in response.json["sessions"]] == ["b"]


@pytest.mark.db
def test_pages_follow_the_next_cursor(client, db_session):
    for minute in range(5):
        add_started_session(db_session, f"s-{minute}", started_at=at(minute))
    headers = bearer(new_key(db_session))

    seen, after = [], ""
    while True:
        page = client.get(f"/api/v1/sessions?limit=2&after={after}", headers=headers).json
        seen += [s["external_id"] for s in page["sessions"]]
        if page["next"] is None:
            break
        after = page["next"]

    assert seen == ["s-4", "s-3", "s-2", "s-1", "s-0"]


@pytest.mark.db
@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("limit=0", "limit must be a whole number from 1 to 100"),
        ("limit=101", "limit must be a whole number from 1 to 100"),
        ("limit=ten", "limit must be a whole number from 1 to 100"),
        ("status=paused", "status must be one of: active, stopped"),
        ("after=nonsense", "after is not a cursor from a previous page"),
    ],
)
def test_a_bad_query_is_a_json_400(client, db_session, query, message):
    response = client.get(f"/api/v1/sessions?{query}", headers=bearer(new_key(db_session)))

    assert response.status_code == 400
    assert response.json == {"error": message}


# --- GET /api/v1/sessions/<id> --------------------------------------------------------------


@pytest.mark.db
def test_one_session_with_its_timeline(client, db_session):
    session_id = add_started_session(db_session, "s-1", branch="feat/x")
    edit = {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}
    tests = {"tool_name": "Bash", "tool_input": {"command": "GITHUB_TOKEN=ghp_x pytest -q"}}
    add_event(db_session, "s-1", at(1), hook=edit, session_id=session_id)
    add_event(db_session, "s-1", at(2), hook=tests, session_id=session_id)

    response = client.get(f"/api/v1/sessions/{session_id}", headers=bearer(new_key(db_session)))

    assert response.status_code == 200
    body = response.json
    assert body["session"]["id"] == session_id
    assert body["session"]["branch"] == "feat/x"
    assert body["files_touched"] == ["src/app.py"]
    assert body["test_runs"] == 1
    assert body["pull_requests"] == []
    assert body["entries"] == [
        {
            "occurred_at": "2026-11-16T10:01:00+00:00",
            "kind": "edit",
            "type": "PostToolUse",
            "tool_name": "Edit",
            "file_path": "src/app.py",
            "command": None,
        },
        {
            "occurred_at": "2026-11-16T10:02:00+00:00",
            "kind": "test_run",
            "type": "PostToolUse",
            "tool_name": "Bash",
            "file_path": None,
            "command": "GITHUB_TOKEN=*** pytest -q",  # masked, as on the dashboard
        },
    ]


@pytest.mark.db
def test_an_unknown_session_is_a_json_404(client, db_session):
    response = client.get("/api/v1/sessions/999999", headers=bearer(new_key(db_session)))

    assert response.status_code == 404
    assert response.json == {"error": "no session with id 999999"}
