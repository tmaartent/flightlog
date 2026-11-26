"""The digests' read side for the MCP tools: attempts on a file, and one session."""

import dataclasses

import pytest

from flightlog.infrastructure.agent_session_queries import SqlDigestQueries
from flightlog.infrastructure.digest_repository import SqlDigestRepository
from tests.infrastructure.test_digests_sql import a_digest
from tests.session_util import add_started_session, at


def with_files(db_session, name, minutes, files, repo="shop"):
    session_id = add_started_session(db_session, name, started_at=at(minutes), repo=repo)
    SqlDigestRepository(db_session).save(
        dataclasses.replace(a_digest(session_id, 1), files_touched=files)
    )
    return session_id


@pytest.mark.db
def test_attempts_on_a_path_newest_first_in_one_repo(db_session):
    old = with_files(db_session, "old", 0, ["src/cart.py", "README.md"])
    new = with_files(db_session, "new", 10, ["src/cart.py"])
    with_files(db_session, "other-file", 20, ["src/cart_test.py"])  # not a prefix match
    with_files(db_session, "other-repo", 30, ["src/cart.py"], repo="web")

    found = SqlDigestQueries(db_session).attempts_on("shop", "src/cart.py", 10)

    assert [s.id for s in found] == [new, old]


@pytest.mark.db
def test_one_session_with_or_without_its_digest(db_session):
    digested = with_files(db_session, "s-1", 0, ["a.py"])
    bare = add_started_session(db_session, "s-2", started_at=at(5), repo="shop")
    queries = SqlDigestQueries(db_session)

    assert queries.one(digested).digest.files_touched == ["a.py"]
    assert queries.one(bare).digest is None
    assert queries.one(999999) is None
