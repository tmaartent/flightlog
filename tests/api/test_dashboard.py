"""The dashboard's HTML through Flask's test client: what each page shows, and the rules.

User journeys through a real browser are in tests/e2e/.
"""

import re

import pytest

from flightlog.domain import AgentSessionStatus, PullRequest, PullRequestState
from tests.session_util import T0, add_event, add_started_session, at


@pytest.fixture
def small_pages(app):
    app.config["DASHBOARD_PAGE_SIZE"] = 2


def session_links(html: str) -> list[str]:
    return re.findall(r'href="/sessions/(\d+)"', html)


@pytest.mark.db
def test_the_root_redirects_to_the_session_list(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"] == "/sessions"


@pytest.mark.db
def test_the_list_shows_each_session_with_a_link_to_its_timeline(client, db_session):
    session_id = add_started_session(db_session, "s-1", repo="flightlog", branch="feat/dashboard")

    response = client.get("/sessions")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "flightlog" in response.text
    assert "feat/dashboard" in response.text
    assert "active" in response.text
    assert "2026-11-16 10:00 UTC" in response.text
    assert session_links(response.text) == [str(session_id)]


@pytest.mark.db
def test_an_empty_list_says_so(client):
    response = client.get("/sessions")

    assert "No sessions" in response.text


@pytest.mark.db
def test_the_list_is_filtered_by_repo_and_status(client, db_session):
    match = add_started_session(db_session, "a", repo="api", status=AgentSessionStatus.STOPPED)
    add_started_session(db_session, "b", repo="web", status=AgentSessionStatus.STOPPED)
    add_started_session(db_session, "c", repo="api")

    response = client.get("/sessions?repo=api&status=stopped")

    assert session_links(response.text) == [str(match)]


@pytest.mark.db
def test_empty_filter_fields_mean_any(client, db_session):
    add_started_session(db_session, "a", repo="api")

    response = client.get("/sessions?repo=&status=")

    assert response.status_code == 200
    assert len(session_links(response.text)) == 1


@pytest.mark.db
def test_the_repo_filter_offers_every_repo(client, db_session):
    add_started_session(db_session, "a", repo="web")
    add_started_session(db_session, "b", repo="api")

    response = client.get("/sessions")

    assert re.findall(r'<option value="(api|web)"', response.text) == ["api", "web"]


@pytest.mark.db
@pytest.mark.parametrize("query", ["status=paused", "after=not-a-cursor"])
def test_a_bad_filter_is_a_400(client, query):
    response = client.get(f"/sessions?{query}")

    assert response.status_code == 400


@pytest.mark.db
@pytest.mark.usefixtures("small_pages")
def test_older_sessions_are_one_link_away(client, db_session):
    ids = [add_started_session(db_session, f"s-{m}", at(m)) for m in range(3)]

    first = client.get("/sessions")
    older = re.search(r'<a href="(/sessions\?[^"]+)"[^>]*>Older', first.text)
    assert older is not None
    second = client.get(older.group(1).replace("&amp;", "&"))

    assert session_links(first.text) == [str(ids[2]), str(ids[1])]
    assert session_links(second.text) == [str(ids[0])]
    assert "Older" not in second.text


@pytest.mark.db
@pytest.mark.usefixtures("small_pages")
def test_the_older_link_keeps_the_filters(client, db_session):
    for minute in range(3):
        add_started_session(db_session, f"s-{minute}", at(minute), repo="api")

    response = client.get("/sessions?repo=api&status=active")

    older = re.search(r'<a href="(/sessions\?[^"]+)"[^>]*>Older', response.text)
    assert older is not None
    assert "repo=api" in older.group(1)
    assert "status=active" in older.group(1)


@pytest.mark.db
def test_the_list_shows_events_still_waiting_for_the_worker(client, db_session):
    add_started_session(db_session, "s-1")
    add_event(db_session, "s-1", at(1), job=True)
    add_event(db_session, "s-1", at(2), job=True)

    response = client.get("/sessions")

    assert "2 pending" in response.text


@pytest.mark.db
def test_an_unknown_session_is_a_404(client):
    assert client.get("/sessions/999999").status_code == 404


@pytest.mark.db
def test_the_timeline_shows_what_the_session_did(client, db_session):
    session_id = add_started_session(db_session, "s-1", branch="feat/x")
    add_event(db_session, "s-1", at(0), {"hook_event_name": "SessionStart"}, session_id)
    edit = {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}}
    add_event(db_session, "s-1", at(1), edit, session_id)
    bash = {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}}
    add_event(db_session, "s-1", at(2), bash, session_id)

    response = client.get(f"/sessions/{session_id}")

    assert response.status_code == 200
    html = response.text
    assert "SessionStart" in html
    assert "src/app.py" in html
    assert "pytest -q" in html
    assert "1 test run" in html
    assert html.index("SessionStart") < html.index("pytest -q")


@pytest.mark.db
def test_the_timeline_shows_the_linked_pull_request_and_its_outcome(client, db_session):
    session_id = add_started_session(db_session, "s-1", branch="feat/x")
    db_session.add(
        PullRequest(
            "flightlog",
            7,
            "feat/x",
            "Add the dashboard",
            updated_at=T0,
            state=PullRequestState.MERGED,
            merged_at=T0,
        )
    )
    db_session.flush()

    response = client.get(f"/sessions/{session_id}")

    assert "#7" in response.text
    assert "Add the dashboard" in response.text
    assert "merged" in response.text


@pytest.mark.db
def test_the_timeline_masks_secrets_in_commands(client, db_session):
    session_id = add_started_session(db_session, "s-1")
    bash = {"tool_name": "Bash", "tool_input": {"command": "GITHUB_TOKEN=ghp_secret123 gh pr list"}}
    add_event(db_session, "s-1", at(1), bash, session_id)

    response = client.get(f"/sessions/{session_id}")

    assert "ghp_secret123" not in response.text
    assert "GITHUB_TOKEN=***" in response.text


@pytest.mark.db
def test_payload_text_is_escaped_not_rendered(client, db_session):
    """Hook payloads are untrusted: a path can carry markup copied from a web page."""
    session_id = add_started_session(db_session, "s-1", branch="<b>branch</b>")
    edit = {"tool_name": "Write", "tool_input": {"file_path": "<script>alert(1)</script>"}}
    add_event(db_session, "s-1", at(1), edit, session_id)

    response = client.get(f"/sessions/{session_id}")

    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<b>branch</b>" not in response.text
