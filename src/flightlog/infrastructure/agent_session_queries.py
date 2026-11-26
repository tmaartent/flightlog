import datetime
from collections import defaultdict

from sqlalchemy import and_, exists, func, select, tuple_
from sqlalchemy.orm import Session, aliased

from flightlog.contracts.report import ReportSession
from flightlog.contracts.sessions import (
    LinkedPullRequest,
    PullRequestOutcome,
    SessionCursor,
    SessionFilter,
    SessionPage,
    SessionSummary,
)
from flightlog.contracts.timeline import SessionEvent
from flightlog.domain import PullRequestState
from flightlog.infrastructure.db import get_session
from flightlog.infrastructure.tables import agent_sessions, event_jobs, event_logs, pull_requests


class SqlAgentSessionQueries:
    """AgentSessionQueries on PostgreSQL: plain SELECTs on the tables, no domain objects."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def linked_pull_requests(self, session_id: int) -> list[LinkedPullRequest]:
        statement = _linked_pull_requests().where(agent_sessions.c.id == session_id)
        return [_linked_pull_request(row) for row in self._session.execute(statement)]

    def list_sessions(self, session_filter: SessionFilter) -> SessionPage:
        s = agent_sessions
        statement = _summaries().order_by(s.c.started_at.desc(), s.c.id.desc())
        if session_filter.repo is not None:
            statement = statement.where(s.c.repo == session_filter.repo)
        if session_filter.status is not None:
            statement = statement.where(s.c.status == session_filter.status)
        if session_filter.after is not None:
            # Keyset paging (ADR-0010): a row tuple comparison matches the ORDER BY exactly,
            # so a session that arrives between two pages never shifts the next one.
            after = session_filter.after
            statement = statement.where(
                tuple_(s.c.started_at, s.c.id) < tuple_(after.started_at, after.id)
            )
        # One row more than the page: if it comes back, there is a next page.
        rows = self._session.execute(statement.limit(session_filter.limit + 1)).all()
        sessions = [_summary(row) for row in rows[: session_filter.limit]]
        has_more = len(rows) > session_filter.limit
        last = sessions[-1] if has_more else None
        return SessionPage(
            sessions=sessions,
            next_cursor=SessionCursor(last.started_at, last.id) if last else None,
        )

    def repos(self) -> list[str]:
        statement = select(agent_sessions.c.repo).distinct().order_by(agent_sessions.c.repo)
        return list(self._session.scalars(statement))

    def session_summary(self, session_id: int) -> SessionSummary | None:
        row = self._session.execute(
            _summaries().where(agent_sessions.c.id == session_id)
        ).one_or_none()
        return _summary(row) if row else None

    def session_events(self, session_id: int) -> list[SessionEvent]:
        statement = _session_events().where(event_logs.c.agent_session_id == session_id)
        return [_session_event(row) for row in self._session.execute(statement)]


class SqlReportQueries:
    """ReportQueries on PostgreSQL (ADR-0016): the same SELECTs as the dashboard, for a week."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def sessions_started(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> list[ReportSession]:
        s = agent_sessions
        rows = self._session.execute(
            select(s.c.id, s.c.repo, s.c.branch, s.c.status, s.c.started_at, s.c.ended_at)
            .where(s.c.started_at >= start, s.c.started_at < end)
            .order_by(s.c.started_at, s.c.id)
        ).all()
        linked: dict[int, list[LinkedPullRequest]] = defaultdict(list)
        if rows:
            ids = [row.id for row in rows]
            statement = _linked_pull_requests().where(agent_sessions.c.id.in_(ids))
            for row in self._session.execute(statement):
                linked[row.session_id].append(_linked_pull_request(row))
        return [
            ReportSession(
                id=row.id,
                repo=row.repo,
                branch=row.branch,
                status=row.status,
                started_at=row.started_at,
                ended_at=row.ended_at,
                pull_requests=linked[row.id],
            )
            for row in rows
        ]

    def events_of(self, session_ids: list[int]) -> dict[int, list[SessionEvent]]:
        events: dict[int, list[SessionEvent]] = {i: [] for i in session_ids}
        if session_ids:
            statement = _session_events().where(event_logs.c.agent_session_id.in_(session_ids))
            for row in self._session.execute(statement):
                events[row.session_id].append(_session_event(row))
        return events


def _linked_pull_requests():
    """PRs opened from a session's branch in its repo (ADR-0009), with the session's id."""
    pr = pull_requests
    revert = aliased(pull_requests)
    # Derived on read: a revert that is still open has undone nothing yet.
    reverted = exists().where(
        revert.c.repo == pr.c.repo,
        revert.c.reverts == pr.c.number,
        revert.c.state == PullRequestState.MERGED,
    )
    return (
        select(
            agent_sessions.c.id.label("session_id"),
            pr.c.number,
            pr.c.title,
            pr.c.state,
            reverted.label("reverted"),
        )
        .join_from(
            agent_sessions,
            pr,
            and_(pr.c.repo == agent_sessions.c.repo, pr.c.branch == agent_sessions.c.branch),
        )
        .order_by(pr.c.number)
    )


def _linked_pull_request(row) -> LinkedPullRequest:
    return LinkedPullRequest(
        number=row.number,
        title=row.title,
        outcome=(
            PullRequestOutcome.REVERTED
            if row.state is PullRequestState.MERGED and row.reverted
            else PullRequestOutcome(row.state.value)
        ),
    )


def _session_events():
    """The fields of applied events that the timeline reads, with their session's id."""
    hook = event_logs.c.payload["hook"]
    tool_input = hook["tool_input"]
    return (
        select(
            event_logs.c.agent_session_id.label("session_id"),
            event_logs.c.id,
            event_logs.c.type,
            event_logs.c.occurred_at,
            hook["tool_name"].astext.label("tool_name"),
            # NotebookEdit names its file notebook_path; every other edit tool file_path.
            func.coalesce(tool_input["file_path"].astext, tool_input["notebook_path"].astext).label(
                "file_path"
            ),
            tool_input["command"].astext.label("command"),
        )
        # The sender's clock decides the order (ADR-0004); id only breaks ties.
        .order_by(event_logs.c.occurred_at, event_logs.c.id)
    )


def _session_event(row) -> SessionEvent:
    return SessionEvent(
        id=row.id,
        type=row.type,
        occurred_at=row.occurred_at,
        tool_name=row.tool_name,
        file_path=row.file_path,
        command=row.command,
    )


def _summaries():
    """SELECT for session summaries, with the pending-event count as a correlated subquery.

    The worker sets event_logs.agent_session_id only when it applies an event, so a pending
    event is matched on its source and the session id in its payload (ADR-0010).
    """
    s = agent_sessions
    pending = (
        select(func.count())
        .select_from(event_jobs)
        .join(event_logs, event_logs.c.id == event_jobs.c.event_log_id)
        .where(
            event_jobs.c.failed_at.is_(None),
            event_logs.c.source == s.c.source,
            event_logs.c.payload["hook"]["session_id"].astext == s.c.external_id,
        )
        .correlate(s)
        .scalar_subquery()
    )
    return select(
        s.c.id,
        s.c.source,
        s.c.external_id,
        s.c.repo,
        s.c.branch,
        s.c.status,
        s.c.started_at,
        s.c.ended_at,
        pending.label("pending_events"),
    )


def _summary(row) -> SessionSummary:
    return SessionSummary(
        id=row.id,
        source=row.source,
        external_id=row.external_id,
        repo=row.repo,
        branch=row.branch,
        status=row.status,
        started_at=row.started_at,
        ended_at=row.ended_at,
        pending_events=row.pending_events,
    )


def request_agent_session_queries() -> SqlAgentSessionQueries:
    """The read side on the current request's session (closed in teardown, see db.py)."""
    return SqlAgentSessionQueries(get_session())


def request_report_queries() -> SqlReportQueries:
    return SqlReportQueries(get_session())
