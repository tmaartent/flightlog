"""GET /api/v1/summaries and /api/v1/sessions/<id>/summary: digests for the client (ADR-0020)."""

import dataclasses
import datetime

import pytest
from sqlalchemy import select

from flightlog.application.api_keys import issue_key
from flightlog.domain import AgentSessionStatus, PullRequest, PullRequestState
from flightlog.infrastructure.digest_repository import SqlDigestRepository
from flightlog.infrastructure.tables import agent_sessions, audit_log
from flightlog.infrastructure.unit_of_work import SqlUnitOfWork
from tests.infrastructure.test_digests_sql import a_digest
from tests.session_util import add_started_session, at

NOW = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)


@pytest.fixture
def headers(db_session):
    key = issue_key("client", SqlUnitOfWork(db_session), NOW).key
    return {"Authorization": f"Bearer {key}"}


def finished(db_session, name, minutes, files=("src/a.py",), repo="shop", branch="feat/x"):
    session_id = add_started_session(
        db_session,
        name,
        started_at=at(minutes),
        repo=repo,
        branch=branch,
        status=AgentSessionStatus.STOPPED,
    )
    db_session.execute(
        agent_sessions.update()
        .where(agent_sessions.c.id == session_id)
        .values(ended_at=at(minutes + 10))
    )
    stored = dataclasses.replace(a_digest(session_id, 2), files_touched=list(files))
    SqlDigestRepository(db_session).save(stored)
    return session_id


@pytest.mark.db
def test_summaries_need_a_key(client):
    assert client.get("/api/v1/summaries?repo=shop").status_code == 401


@pytest.mark.db
def test_summaries_need_a_repo(client, headers):
    response = client.get("/api/v1/summaries", headers=headers)

    assert response.status_code == 400
    assert response.json == {"error": "repo is required"}


@pytest.mark.db
def test_summaries_newest_first_in_the_shared_json_shape(client, db_session, headers):
    older = finished(db_session, "older", 0)
    newer = finished(db_session, "newer", 30)
    finished(db_session, "elsewhere", 60, repo="web")
    db_session.add(PullRequest("shop", 3, "feat/x", "Cart", at(50), state=PullRequestState.MERGED))
    db_session.flush()

    body = client.get("/api/v1/summaries?repo=shop", headers=headers).json

    assert [s["id"] for s in body["summaries"]] == [newer, older]
    assert body["next"] is None
    first = body["summaries"][0]
    assert first["pull_request"] == {"number": 3, "title": "Cart", "outcome": "merged"}
    assert first["summary"]["files_touched"] == ["src/a.py"]
    assert first["summary_state"] == "ready"


@pytest.mark.db
def test_summaries_are_paged_without_repeats(client, db_session, headers):
    for n in range(5):
        finished(db_session, f"s-{n}", n)

    seen, after = [], ""
    while True:
        page = client.get(f"/api/v1/summaries?repo=shop&limit=2&after={after}", headers=headers)
        seen += [s["id"] for s in page.json["summaries"]]
        if page.json["next"] is None:
            break
        after = page.json["next"]

    assert len(seen) == len(set(seen)) == 5


@pytest.mark.db
def test_summaries_filtered_by_path_and_since(client, db_session, headers):
    finished(db_session, "old-hit", 0, files=["src/cart.py"])
    recent_hit = finished(db_session, "recent-hit", 3 * 24 * 60, files=["src/cart.py"])
    finished(db_session, "recent-miss", 3 * 24 * 60 + 5, files=["src/other.py"])

    body = client.get(
        "/api/v1/summaries?repo=shop&path=src/cart.py&since=2026-11-18", headers=headers
    ).json

    assert [s["id"] for s in body["summaries"]] == [recent_hit]


@pytest.mark.db
@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("since=18-11-2026", "since must be a date like 2026-11-01"),
        ("limit=101", "limit must be a whole number from 1 to 100"),
        ("after=nope", "after is not a cursor from a previous page"),
    ],
)
def test_bad_summary_filters_are_a_400(client, headers, query, message):
    response = client.get(f"/api/v1/summaries?repo=shop&{query}", headers=headers)

    assert response.status_code == 400
    assert response.json == {"error": message}


@pytest.mark.db
def test_one_session_summary(client, db_session, headers):
    session_id = finished(db_session, "s-1", 0)

    found = client.get(f"/api/v1/sessions/{session_id}/summary", headers=headers)
    missing = client.get("/api/v1/sessions/999999/summary", headers=headers)

    assert found.status_code == 200
    assert found.json["session"]["id"] == session_id
    assert missing.status_code == 404
    assert missing.json == {"error": "no session with id 999999"}


@pytest.mark.db
def test_summary_calls_are_audited_with_their_object(client, db_session, headers):
    session_id = finished(db_session, "s-1", 0)

    client.get(f"/api/v1/sessions/{session_id}/summary", headers=headers)

    (row,) = db_session.execute(select(audit_log)).all()
    assert (row.endpoint, row.object_type, row.object_id) == (
        "read_api.session_summary",
        "session",
        str(session_id),
    )
