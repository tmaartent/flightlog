"""The client against the real read API, through Flask's test client (ADR-0020).

The transport is the only stand-in: requests go through the app's routes, auth, rate limits
and JSON, so these are also contract tests between the server's JSON and the client's types.
"""

import dataclasses
import datetime
import urllib.parse

import pytest
from flightlog_client import (
    Flightlog,
    NotFound,
    Outcome,
    RateLimited,
    SummaryState,
    Unauthorized,
)

from flightlog.application.api_keys import issue_key
from flightlog.domain import AgentSessionStatus, PullRequest, PullRequestState
from flightlog.infrastructure.digest_repository import SqlDigestRepository
from flightlog.infrastructure.tables import agent_sessions
from flightlog.infrastructure.unit_of_work import SqlUnitOfWork
from tests.harness import make_test_app
from tests.infrastructure.test_digests_sql import a_digest
from tests.session_util import add_event, add_started_session, at

NOW = datetime.datetime(2026, 11, 26, 10, 0, tzinfo=datetime.UTC)
pytestmark = pytest.mark.db


def through(flask_client):
    """A Transport that sends the client's GETs into the app, without a server."""

    def send(url, headers):
        parts = urllib.parse.urlsplit(url)
        response = flask_client.get(f"{parts.path}?{parts.query}", headers=headers)
        return response.status_code, dict(response.headers), response.data

    return send


@pytest.fixture
def key(db_session):
    return issue_key("script", SqlUnitOfWork(db_session), NOW).key


@pytest.fixture
def fl(client, key):
    return Flightlog("http://flightlog.test", key, transport=through(client))


def finished(db_session, name, minutes, files=("src/a.py",), branch="feat/x"):
    session_id = add_started_session(
        db_session,
        name,
        started_at=at(minutes),
        repo="shop",
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


def test_recent_sessions_are_typed(fl, db_session):
    session_id = finished(db_session, "s-1", 0)
    db_session.add(PullRequest("shop", 9, "feat/x", "Cart", at(30), state=PullRequestState.MERGED))
    db_session.flush()

    (session,) = fl.recent_sessions("shop")

    assert session.id == session_id
    assert session.started_at == at(0)
    assert session.ended_at == at(10)
    assert session.goal == "Cart"
    assert session.pull_request.number == 9
    assert session.pull_request.outcome is Outcome.MERGED
    assert session.summary_state is SummaryState.READY
    assert session.summary.files_touched == ["src/a.py"]
    assert session.summary.duration_seconds == 60


def test_attempts_on_and_session_summary(fl, db_session):
    hit = finished(db_session, "hit", 0, files=["src/cart.py"])
    finished(db_session, "miss", 5, files=["src/other.py"])

    assert [s.id for s in fl.attempts_on("src/cart.py", repo="shop")] == [hit]
    assert fl.session_summary(hit).id == hit
    with pytest.raises(NotFound):
        fl.session_summary(999999)


def test_summaries_iterate_over_every_page(fl, db_session):
    ids = [finished(db_session, f"s-{n}", n) for n in range(5)]

    seen = [s.id for s in fl.summaries("shop", page_size=2)]

    assert seen == list(reversed(ids))


def test_summaries_since_a_date(fl, db_session):
    finished(db_session, "old", 0)
    recent = finished(db_session, "recent", 3 * 24 * 60)

    found = fl.summaries("shop", since=datetime.date(2026, 11, 18))

    assert [s.id for s in found] == [recent]


def test_sessions_and_a_timeline(fl, db_session):
    session_id = finished(db_session, "s-1", 0)
    add_event(
        db_session,
        "s-1",
        at(1),
        hook={"tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}},
        session_id=session_id,
    )

    (row,) = list(fl.sessions(repo="shop"))
    timeline = fl.timeline(session_id)

    assert (row.id, row.repo, row.status) == (session_id, "shop", "stopped")
    assert timeline.session.id == session_id
    assert timeline.files_touched == ["src/a.py"]
    assert timeline.entries[0].kind == "edit"


def test_a_wrong_key_is_unauthorized(client):
    fl = Flightlog("http://flightlog.test", "fl_0a1b2c3d_wrong", transport=through(client))

    with pytest.raises(Unauthorized) as raised:
        fl.recent_sessions("shop")

    assert raised.value.message == "invalid or missing API key"


def test_over_the_limit_is_rate_limited_with_retry_after(db_connection, db_session, key):
    client = make_test_app(db_connection, RATELIMIT_API="1 per minute").test_client()
    fl = Flightlog("http://flightlog.test", key, transport=through(client))
    fl.recent_sessions("shop")

    with pytest.raises(RateLimited) as raised:
        fl.recent_sessions("shop")

    assert 0 < raised.value.retry_after <= 60


def test_paging_waits_out_one_429(db_connection, db_session, key):
    for n in range(3):
        finished(db_session, f"s-{n}", n)
    client = make_test_app(db_connection, RATELIMIT_API="1 per minute").test_client()
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        # Time "passes": a fresh app has fresh counters, like a new minute.
        nonlocal client
        client = make_test_app(db_connection, RATELIMIT_API="1 per minute").test_client()

    fl = Flightlog(
        "http://flightlog.test", key, transport=lambda u, h: through(client)(u, h), sleep=sleep
    )

    seen = list(fl.summaries("shop", page_size=2))

    assert len(seen) == 3
    assert len(waits) == 1


def test_configuration_comes_from_the_environment(monkeypatch, client, key):
    monkeypatch.setenv("FLIGHTLOG_URL", "http://flightlog.test")
    monkeypatch.setenv("FLIGHTLOG_API_KEY", key)

    assert Flightlog(transport=through(client)).recent_sessions("shop") == []


def test_without_url_or_key_it_says_what_is_missing(monkeypatch):
    monkeypatch.delenv("FLIGHTLOG_URL", raising=False)
    monkeypatch.delenv("FLIGHTLOG_API_KEY", raising=False)

    with pytest.raises(ValueError, match="FLIGHTLOG_API_KEY"):
        Flightlog()


def test_only_http_urls():
    fl = Flightlog("file:///etc", "fl_0a1b2c3d_x")

    with pytest.raises(ValueError, match="not an http"):
        fl.recent_sessions("shop")


def test_the_client_package_never_imports_the_server():
    """No database access by construction (M5 acceptance): it can't even see flightlog."""
    import ast
    from pathlib import Path

    import flightlog_client

    package = Path(flightlog_client.__file__).parent
    imported = set()
    for source in package.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    assert imported.isdisjoint({"flightlog", "sqlalchemy", "psycopg", "flask"})
