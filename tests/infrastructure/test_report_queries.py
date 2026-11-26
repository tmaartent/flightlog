"""The weekly report's two queries, against PostgreSQL."""

import datetime

import pytest

from flightlog.contracts.report import IsoWeek
from flightlog.contracts.sessions import LinkedPullRequest, PullRequestOutcome
from flightlog.domain import PullRequest, PullRequestState
from flightlog.infrastructure.agent_session_queries import SqlReportQueries
from tests.session_util import add_event, add_started_session

WEEK = IsoWeek.parse("2026-W46")


def at(hours: float) -> datetime.datetime:
    return WEEK.start + datetime.timedelta(hours=hours)


@pytest.mark.db
def test_only_sessions_that_started_in_the_week(db_session):
    add_started_session(db_session, "before", started_at=at(-0.01))
    first = add_started_session(db_session, "first", started_at=at(0))  # Monday 00:00 is in
    last = add_started_session(db_session, "last", started_at=at(7 * 24 - 0.01))
    add_started_session(db_session, "after", started_at=at(7 * 24))  # next Monday is out

    sessions = SqlReportQueries(db_session).sessions_started(WEEK.start, WEEK.end)

    assert [s.id for s in sessions] == [first, last]


@pytest.mark.db
def test_sessions_come_with_their_linked_pull_requests(db_session):
    linked = add_started_session(db_session, "s-1", started_at=at(1), branch="feat/x")
    alone = add_started_session(db_session, "s-2", started_at=at(2), branch="feat/y")
    for number, state, reverts in [
        (7, PullRequestState.MERGED, None),
        (8, PullRequestState.MERGED, 7),
    ]:
        db_session.add(
            PullRequest(
                "flightlog",
                number,
                "feat/x" if number == 7 else "revert-7",
                f"PR {number}",
                at(3),
                state=state,
                reverts=reverts,
            )
        )
    db_session.flush()

    by_id = {s.id: s for s in SqlReportQueries(db_session).sessions_started(WEEK.start, WEEK.end)}

    assert by_id[linked].pull_requests == [
        LinkedPullRequest(7, "PR 7", PullRequestOutcome.REVERTED)
    ]
    assert by_id[alone].pull_requests == []


@pytest.mark.db
def test_events_are_grouped_by_session_in_timeline_order(db_session):
    one = add_started_session(db_session, "s-1", started_at=at(0))
    two = add_started_session(db_session, "s-2", started_at=at(1))
    add_event(db_session, "s-1", at(2), hook={"tool_name": "Bash"}, session_id=one)
    add_event(
        db_session,
        "s-1",
        at(1),
        hook={"tool_name": "Edit", "tool_input": {"file_path": "a.py"}},
        session_id=one,
    )

    events = SqlReportQueries(db_session).events_of([one, two])

    assert [(e.tool_name, e.file_path) for e in events[one]] == [("Edit", "a.py"), ("Bash", None)]
    assert events[two] == []


@pytest.mark.db
def test_no_sessions_means_no_queries_with_an_empty_in(db_session):
    queries = SqlReportQueries(db_session)

    assert queries.sessions_started(WEEK.start, WEEK.end) == []
    assert queries.events_of([]) == {}
