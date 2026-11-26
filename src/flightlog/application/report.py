"""The weekly report (ADR-0016): per repo, what the agents did in one ISO week.

Counts come from the same `classify` as the timeline, so "a test run" means one thing in
the dashboard, the API and the PDF. Commands are counted, never copied into the report.
"""

import datetime
from collections import Counter, defaultdict

from flightlog.application.ports import ReportQueries
from flightlog.application.timeline import classify
from flightlog.contracts.report import IsoWeek, ReportRow, ReportSession, RepoWeek, WeeklyReport
from flightlog.contracts.sessions import LinkedPullRequest, PullRequestOutcome
from flightlog.contracts.timeline import SessionEvent, TimelineEntryKind
from flightlog.domain import AgentSessionStatus

ROW_LIMIT = 20  # with the summary and the top files, the most that fits on one A4 page
TOP_FILES = 10


def weekly_report(
    week: IsoWeek, queries: ReportQueries, generated_at: datetime.datetime
) -> WeeklyReport:
    sessions = queries.sessions_started(week.start, week.end)
    events = queries.events_of([s.id for s in sessions])

    by_repo: dict[str, list[ReportSession]] = defaultdict(list)
    for session in sessions:
        by_repo[session.repo].append(session)

    return WeeklyReport(
        week=week,
        generated_at=generated_at,
        repos=[_repo_week(repo, by_repo[repo], events) for repo in sorted(by_repo)],
    )


def _repo_week(
    repo: str, sessions: list[ReportSession], events: dict[int, list[SessionEvent]]
) -> RepoWeek:
    edited: Counter[str] = Counter()
    rows: list[ReportRow] = []
    for session in sorted(sessions, key=lambda s: (s.started_at, s.id), reverse=True):
        kinds = [(classify(e), e) for e in events.get(session.id, [])]
        edits = [e.file_path for kind, e in kinds if kind is TimelineEntryKind.EDIT and e.file_path]
        edited.update(edits)
        rows.append(
            ReportRow(
                started_at=session.started_at,
                ended_at=session.ended_at,
                branch=session.branch,
                edits=len(edits),
                test_runs=sum(1 for kind, _ in kinds if kind is TimelineEntryKind.TEST_RUN),
                pull_request=max(session.pull_requests, key=lambda p: p.number, default=None),
            )
        )

    stopped = [s for s in sessions if s.status is AgentSessionStatus.STOPPED and s.ended_at]
    return RepoWeek(
        repo=repo,
        sessions=len(sessions),
        stopped=len(stopped),
        active=len(sessions) - len(stopped),
        time_spent=sum((s.ended_at - s.started_at for s in stopped), datetime.timedelta()),
        test_runs=sum(row.test_runs for row in rows),
        pull_requests=_count_outcomes(sessions),
        # Most edits first; equal counts by path, so the order is stable.
        top_files=sorted(edited.items(), key=lambda item: (-item[1], item[0]))[:TOP_FILES],
        rows=rows[:ROW_LIMIT],
        rows_not_shown=max(0, len(rows) - ROW_LIMIT),
    )


def _count_outcomes(sessions: list[ReportSession]) -> dict[PullRequestOutcome, int]:
    """Each PR once, even when several sessions worked on its branch."""
    distinct: dict[int, LinkedPullRequest] = {}
    for session in sessions:
        for pr in session.pull_requests:
            distinct[pr.number] = pr
    counts = Counter(pr.outcome for pr in distinct.values())
    return {outcome: counts[outcome] for outcome in PullRequestOutcome}
