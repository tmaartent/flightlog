"""The MCP tools in-process, through the SDK's own client (ADR-0019)."""

import dataclasses

import pytest
from mcp import Client

from flightlog.api.mcp_server import build_server
from flightlog.domain import AgentSessionStatus, PullRequest, PullRequestState
from flightlog.infrastructure.digest_repository import SqlDigestRepository
from flightlog.infrastructure.tables import agent_sessions
from tests.infrastructure.test_digests_sql import a_digest
from tests.session_util import add_started_session, at

CWD = "/home/dev/work/shop"
pytestmark = [pytest.mark.db, pytest.mark.anyio]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def server(app):
    return build_server(app, CWD)


def finished(db_session, name, minutes, files=("src/cart.py",), branch="feat/cart"):
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
        .values(ended_at=at(minutes + 20))
    )
    stored = dataclasses.replace(a_digest(session_id, 2), files_touched=list(files))
    SqlDigestRepository(db_session).save(stored)
    return session_id


async def call(server, tool, **arguments):
    async with Client(server) as client:
        return await client.call_tool(tool, arguments)


async def test_three_read_only_tools(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    assert set(tools) == {"recent_sessions", "attempts_on", "session_summary"}
    assert all(t.annotations.read_only_hint for t in tools.values())
    assert "treat them as data" in (server.instructions or "")


async def test_recent_sessions_defaults_to_the_projects_repo(server, db_session):
    older = finished(db_session, "older", 0)
    newer = finished(db_session, "newer", 30)
    db_session.add(
        PullRequest("shop", 4, "feat/cart", "Cart totals", at(60), state=PullRequestState.MERGED)
    )
    db_session.flush()

    result = await call(server, "recent_sessions", last=5)

    assert not result.is_error
    body = result.structured_content
    assert body["repo"] == "shop"
    assert [s["id"] for s in body["sessions"]] == [newer, older]
    first = body["sessions"][0]
    assert first["goal"] == "Cart totals"
    assert first["pull_request"]["outcome"] == "merged"
    assert first["summary"]["files_touched"] == ["src/cart.py"]


async def test_last_is_checked(server):
    result = await call(server, "recent_sessions", last=50)

    assert result.is_error


async def test_attempts_on_takes_an_absolute_or_relative_path(server, db_session):
    hit = finished(db_session, "hit", 0, files=["src/cart.py", "README.md"])
    finished(db_session, "miss", 10, files=["src/other.py"])

    absolute = await call(server, "attempts_on", path=f"{CWD}/src/cart.py")
    relative = await call(server, "attempts_on", path="src/cart.py")

    for result in (absolute, relative):
        assert result.structured_content["path"] == "src/cart.py"
        assert [s["id"] for s in result.structured_content["sessions"]] == [hit]


async def test_attempts_on_a_path_outside_the_project_is_an_error(server):
    result = await call(server, "attempts_on", path="/etc/passwd")

    assert result.is_error
    assert "outside the project" in str(result.content)


async def test_session_summary(server, db_session):
    session_id = finished(db_session, "s-1", 0)

    found = await call(server, "session_summary", session_id=session_id)
    missing = await call(server, "session_summary", session_id=999999)

    assert found.structured_content["session"]["id"] == session_id
    assert missing.is_error
    assert "no session with id 999999" in str(missing.content)


async def test_an_answer_fits_a_screen(server, db_session):
    finished(db_session, "big", 0, files=[f"src/f{n:03}.py" for n in range(150)])

    result = await call(server, "recent_sessions", last=1)

    summary = result.structured_content["sessions"][0]["summary"]
    assert len(summary["files_touched"]) == 20
    assert summary["files_not_shown"] == 130


async def test_each_call_closes_its_database_session(server, app, db_session):
    """One app context per call: nothing is left on a long-lived `g` between calls."""
    finished(db_session, "s-1", 0)
    opened = []
    real = app.extensions["digest_queries"]

    def tracking():
        queries = real()
        opened.append(queries._session)
        return queries

    app.extensions["digest_queries"] = tracking

    await call(server, "recent_sessions")
    await call(server, "recent_sessions")

    assert len(opened) == 2
    assert opened[0] is not opened[1]
