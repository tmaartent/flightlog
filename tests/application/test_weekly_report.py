import datetime

from flightlog.application.report import ROW_LIMIT, TOP_FILES, weekly_report
from flightlog.contracts.report import IsoWeek, ReportSession
from flightlog.contracts.sessions import LinkedPullRequest, PullRequestOutcome
from flightlog.contracts.timeline import SessionEvent
from flightlog.domain import AgentSessionStatus

WEEK = IsoWeek.parse("2026-W46")
NOW = datetime.datetime(2026, 11, 26, 9, 0, tzinfo=datetime.UTC)
MERGED = PullRequestOutcome.MERGED


def at(hours: float) -> datetime.datetime:
    return WEEK.start + datetime.timedelta(hours=hours)


class FakeReportQueries:
    def __init__(self) -> None:
        self.sessions: list[ReportSession] = []
        self.events: dict[int, list[SessionEvent]] = {}
        self.asked: list[tuple] = []

    def sessions_started(self, start, end) -> list[ReportSession]:
        self.asked.append((start, end))
        return self.sessions

    def events_of(self, session_ids) -> dict[int, list[SessionEvent]]:
        return {i: self.events.get(i, []) for i in session_ids}

    def add(self, id, repo="flightlog", hours=0.0, minutes=30, prs=(), events=(), **fields):
        stopped = minutes is not None
        self.sessions.append(
            ReportSession(
                id=id,
                repo=repo,
                branch=fields.get("branch"),
                status=AgentSessionStatus.STOPPED if stopped else AgentSessionStatus.ACTIVE,
                started_at=at(hours),
                ended_at=at(hours) + datetime.timedelta(minutes=minutes) if stopped else None,
                pull_requests=list(prs),
            )
        )
        self.events[id] = list(events)


def edit(path: str) -> SessionEvent:
    return SessionEvent(1, "PostToolUse", at(0), tool_name="Edit", file_path=path)


def bash(command: str) -> SessionEvent:
    return SessionEvent(1, "PostToolUse", at(0), tool_name="Bash", command=command)


def test_it_asks_for_the_sessions_that_started_in_the_week():
    queries = FakeReportQueries()

    report = weekly_report(WEEK, queries, NOW)

    assert queries.asked == [(WEEK.start, WEEK.end)]
    assert (report.week, report.generated_at, report.repos) == (WEEK, NOW, [])


def test_one_page_per_repo_sorted_by_name():
    queries = FakeReportQueries()
    queries.add(1, repo="web")
    queries.add(2, repo="api")
    queries.add(3, repo="web")

    report = weekly_report(WEEK, queries, NOW)

    assert [(r.repo, r.sessions) for r in report.repos] == [("api", 1), ("web", 2)]


def test_the_summary_counts_sessions_time_and_test_runs():
    queries = FakeReportQueries()
    queries.add(1, minutes=30, events=[bash("pytest -q"), bash("ls"), edit("a.py")])
    queries.add(2, minutes=45, events=[bash("cd x && npm test")])
    queries.add(3, minutes=None)  # still active: no time counted

    (repo,) = weekly_report(WEEK, queries, NOW).repos

    assert (repo.sessions, repo.stopped, repo.active) == (3, 2, 1)
    assert repo.time_spent == datetime.timedelta(minutes=75)
    assert repo.test_runs == 2


def test_pull_requests_are_counted_once_each_by_outcome():
    queries = FakeReportQueries()
    shared = LinkedPullRequest(7, "Add login", MERGED)
    queries.add(1, prs=[shared])
    queries.add(2, prs=[shared, LinkedPullRequest(8, "Undo", PullRequestOutcome.REVERTED)])

    (repo,) = weekly_report(WEEK, queries, NOW).repos

    assert repo.pull_requests == {
        PullRequestOutcome.OPEN: 0,
        PullRequestOutcome.CLOSED: 0,
        PullRequestOutcome.MERGED: 1,
        PullRequestOutcome.REVERTED: 1,
    }


def test_the_most_edited_files_come_first():
    queries = FakeReportQueries()
    queries.add(1, events=[edit("b.py"), edit("a.py"), edit("b.py")])
    queries.add(2, events=[edit("c.py"), edit("b.py"), bash("cat a.py")])

    (repo,) = weekly_report(WEEK, queries, NOW).repos

    assert repo.top_files == [("b.py", 3), ("a.py", 1), ("c.py", 1)]  # ties by path


def test_only_the_top_files_are_listed():
    queries = FakeReportQueries()
    queries.add(1, events=[edit(f"f{n:02d}.py") for n in range(TOP_FILES + 5)])

    (repo,) = weekly_report(WEEK, queries, NOW).repos

    assert len(repo.top_files) == TOP_FILES


def test_each_row_has_its_counts_and_newest_pull_request():
    queries = FakeReportQueries()
    newest = LinkedPullRequest(9, "Second try", PullRequestOutcome.OPEN)
    queries.add(
        1,
        branch="feat/x",
        events=[edit("a.py"), edit("a.py"), bash("pytest")],
        prs=[LinkedPullRequest(8, "First try", PullRequestOutcome.CLOSED), newest],
    )

    (row,) = weekly_report(WEEK, queries, NOW).repos[0].rows

    assert (row.branch, row.edits, row.test_runs, row.pull_request) == ("feat/x", 2, 1, newest)
    assert row.started_at == at(0)


def test_rows_are_newest_first_and_capped_so_a_repo_fits_on_one_page():
    queries = FakeReportQueries()
    for n in range(ROW_LIMIT + 3):
        queries.add(n + 1, hours=n)

    (repo,) = weekly_report(WEEK, queries, NOW).repos

    assert len(repo.rows) == ROW_LIMIT
    assert repo.rows_not_shown == 3
    assert repo.rows[0].started_at == at(ROW_LIMIT + 2)
    assert repo.sessions == ROW_LIMIT + 3  # the summary still counts every session
