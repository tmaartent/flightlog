"""Linking sessions to pull requests at read time (ADR-0009), on a real database."""

import datetime

import pytest

from flightlog.contracts.ingest import CLAUDE
from flightlog.contracts.sessions import LinkedPullRequest, PullRequestOutcome
from flightlog.domain import AgentSession, PullRequest, PullRequestState
from flightlog.infrastructure.agent_session_queries import SqlAgentSessionQueries

T0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.UTC)
MERGED = {"state": PullRequestState.MERGED, "merged_at": T0}


def add_session(db_session, branch: str | None = "feat/x", repo: str = "flightlog") -> int:
    session = AgentSession(CLAUDE, f"s-{branch}-{repo}", repo, T0, branch=branch)
    db_session.add(session)
    db_session.flush()
    return session.id


def add_pr(db_session, number: int, branch: str = "feat/x", repo: str = "flightlog", **fields):
    db_session.add(PullRequest(repo, number, branch, f"PR {number}", updated_at=T0, **fields))
    db_session.flush()


def linked(db_session, session_id: int) -> list[LinkedPullRequest]:
    return SqlAgentSessionQueries(db_session).linked_pull_requests(session_id)


@pytest.mark.db
def test_a_session_is_linked_to_the_prs_from_its_branch_in_its_repo(db_session):
    session_id = add_session(db_session)
    add_pr(db_session, 7)
    add_pr(db_session, 8, state=PullRequestState.CLOSED)
    add_pr(db_session, 9, branch="feat/other")
    add_pr(db_session, 10, repo="other-repo")

    assert linked(db_session, session_id) == [
        LinkedPullRequest(7, "PR 7", PullRequestOutcome.OPEN),
        LinkedPullRequest(8, "PR 8", PullRequestOutcome.CLOSED),
    ]


@pytest.mark.db
def test_a_merged_pr_is_merged(db_session):
    session_id = add_session(db_session)
    add_pr(db_session, 7, **MERGED)

    (pr,) = linked(db_session, session_id)
    assert pr.outcome is PullRequestOutcome.MERGED


@pytest.mark.db
def test_a_merged_pr_undone_by_a_merged_revert_is_reverted(db_session):
    session_id = add_session(db_session)
    add_pr(db_session, 7, **MERGED)
    add_pr(db_session, 8, branch="revert-7-feat/x", reverts=7, **MERGED)

    (pr,) = linked(db_session, session_id)
    assert pr.outcome is PullRequestOutcome.REVERTED


@pytest.mark.db
def test_an_open_revert_has_not_reverted_anything_yet(db_session):
    session_id = add_session(db_session)
    add_pr(db_session, 7, **MERGED)
    add_pr(db_session, 8, branch="revert-7-feat/x", reverts=7)

    (pr,) = linked(db_session, session_id)
    assert pr.outcome is PullRequestOutcome.MERGED


@pytest.mark.db
def test_a_revert_in_another_repo_does_not_count(db_session):
    session_id = add_session(db_session)
    add_pr(db_session, 7, **MERGED)
    add_pr(db_session, 8, branch="revert-7", repo="other-repo", reverts=7, **MERGED)

    (pr,) = linked(db_session, session_id)
    assert pr.outcome is PullRequestOutcome.MERGED


@pytest.mark.db
def test_a_session_without_a_branch_has_no_prs(db_session):
    session_id = add_session(db_session, branch=None)
    add_pr(db_session, 7)

    assert linked(db_session, session_id) == []
