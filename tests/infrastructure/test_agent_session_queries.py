"""The read side on a real database: PR links (ADR-0009), lists and timelines (ADR-0010)."""

import datetime

import pytest

from flightlog.contracts.ingest import CLAUDE
from flightlog.contracts.sessions import (
    LinkedPullRequest,
    PullRequestOutcome,
    SessionCursor,
    SessionFilter,
)
from flightlog.contracts.timeline import SessionEvent
from flightlog.domain import AgentSession, AgentSessionStatus, PullRequest, PullRequestState
from flightlog.infrastructure.agent_session_queries import SqlAgentSessionQueries
from tests.session_util import add_event, add_started_session, at

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


def queries(db_session) -> SqlAgentSessionQueries:
    return SqlAgentSessionQueries(db_session)


@pytest.mark.db
def test_sessions_are_listed_newest_first(db_session):
    add_started_session(db_session, "old", at(0))
    add_started_session(db_session, "new", at(10))
    add_started_session(db_session, "middle", at(5))

    page = queries(db_session).list_sessions(SessionFilter())

    assert [s.external_id for s in page.sessions] == ["new", "middle", "old"]
    assert page.next_cursor is None


@pytest.mark.db
def test_sessions_that_start_at_the_same_time_are_ordered_by_id(db_session):
    first = add_started_session(db_session, "a", at(0))
    second = add_started_session(db_session, "b", at(0))

    page = queries(db_session).list_sessions(SessionFilter())

    assert [s.id for s in page.sessions] == [second, first]


@pytest.mark.db
def test_a_summary_has_the_session_fields(db_session):
    session_id = add_started_session(
        db_session, "s-1", at(0), repo="api", status=AgentSessionStatus.STOPPED
    )

    (summary,) = queries(db_session).list_sessions(SessionFilter()).sessions

    assert summary.id == session_id
    assert (summary.source, summary.external_id, summary.repo) == (CLAUDE, "s-1", "api")
    assert summary.status is AgentSessionStatus.STOPPED
    assert summary.started_at == at(0)
    assert summary.pending_events == 0


@pytest.mark.db
def test_sessions_are_filtered_by_repo_and_status(db_session):
    add_started_session(db_session, "match", repo="api", status=AgentSessionStatus.STOPPED)
    add_started_session(db_session, "other-repo", repo="web", status=AgentSessionStatus.STOPPED)
    add_started_session(db_session, "still-active", repo="api")

    page = queries(db_session).list_sessions(
        SessionFilter(repo="api", status=AgentSessionStatus.STOPPED)
    )

    assert [s.external_id for s in page.sessions] == ["match"]


@pytest.mark.db
def test_pages_follow_each_other_without_gaps_or_repeats(db_session):
    for minute in range(5):
        add_started_session(db_session, f"s-{minute}", at(minute))
    q = queries(db_session)

    first = q.list_sessions(SessionFilter(limit=2))
    second = q.list_sessions(SessionFilter(limit=2, after=first.next_cursor))
    third = q.list_sessions(SessionFilter(limit=2, after=second.next_cursor))

    assert [s.external_id for s in first.sessions] == ["s-4", "s-3"]
    assert [s.external_id for s in second.sessions] == ["s-2", "s-1"]
    assert [s.external_id for s in third.sessions] == ["s-0"]
    assert third.next_cursor is None


@pytest.mark.db
def test_a_new_session_does_not_shift_the_next_page(db_session):
    for minute in range(3):
        add_started_session(db_session, f"s-{minute}", at(minute))
    q = queries(db_session)
    first = q.list_sessions(SessionFilter(limit=2))

    add_started_session(db_session, "arrived-meanwhile", at(60))
    second = q.list_sessions(SessionFilter(limit=2, after=first.next_cursor))

    assert [s.external_id for s in second.sessions] == ["s-0"]


@pytest.mark.db
def test_the_cursor_points_at_the_last_session_of_the_page(db_session):
    newest = add_started_session(db_session, "a", at(1))
    add_started_session(db_session, "b", at(0))

    page = queries(db_session).list_sessions(SessionFilter(limit=1))

    assert page.next_cursor == SessionCursor(at(1), newest)


@pytest.mark.db
def test_a_full_last_page_has_no_next_cursor(db_session):
    add_started_session(db_session, "a", at(1))
    add_started_session(db_session, "b", at(0))

    page = queries(db_session).list_sessions(SessionFilter(limit=2))

    assert len(page.sessions) == 2
    assert page.next_cursor is None


@pytest.mark.db
def test_pending_events_count_queued_jobs_of_this_session_only(db_session):
    session_id = add_started_session(db_session, "s-1")
    add_started_session(db_session, "s-2")
    add_event(db_session, "s-1", at(1), job=True)  # queued
    add_event(db_session, "s-1", at(2), job=True)  # queued
    add_event(db_session, "s-1", at(3), job=True, failed=True)  # admin page, not pending
    add_event(db_session, "s-1", at(4), session_id=session_id)  # applied, job gone
    add_event(db_session, "s-2", at(5), job=True)  # another session

    summary = queries(db_session).session_summary(session_id)

    assert summary is not None
    assert summary.pending_events == 2


@pytest.mark.db
def test_an_unknown_session_has_no_summary(db_session):
    assert queries(db_session).session_summary(999_999) is None


@pytest.mark.db
def test_repos_are_distinct_and_sorted(db_session):
    add_started_session(db_session, "a", repo="web")
    add_started_session(db_session, "b", repo="api")
    add_started_session(db_session, "c", repo="web")

    assert queries(db_session).repos() == ["api", "web"]


@pytest.mark.db
def test_session_events_are_ordered_by_occurrence_then_id(db_session):
    session_id = add_started_session(db_session, "s-1")
    late = add_event(db_session, "s-1", at(5), session_id=session_id)
    tie_first = add_event(db_session, "s-1", at(1), session_id=session_id)
    tie_second = add_event(db_session, "s-1", at(1), session_id=session_id)

    events = queries(db_session).session_events(session_id)

    assert [e.id for e in events] == [tie_first, tie_second, late]


@pytest.mark.db
def test_session_events_hold_only_the_fields_the_timeline_reads(db_session):
    session_id = add_started_session(db_session, "s-1")
    hook = {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -q"},
        "tool_response": {"stdout": "raw tool text"},
    }
    event_id = add_event(db_session, "s-1", at(1), hook, session_id=session_id)

    assert queries(db_session).session_events(session_id) == [
        SessionEvent(event_id, "PostToolUse", at(1), "Bash", file_path=None, command="pytest -q")
    ]


@pytest.mark.db
def test_a_notebook_edit_reports_its_notebook_path(db_session):
    session_id = add_started_session(db_session, "s-1")
    hook = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "a.ipynb"}}
    add_event(db_session, "s-1", at(1), hook, session_id=session_id)

    (event,) = queries(db_session).session_events(session_id)
    assert event.file_path == "a.ipynb"


@pytest.mark.db
def test_events_not_yet_applied_are_not_on_the_timeline(db_session):
    session_id = add_started_session(db_session, "s-1")
    add_event(db_session, "s-1", at(1), job=True)

    assert queries(db_session).session_events(session_id) == []
