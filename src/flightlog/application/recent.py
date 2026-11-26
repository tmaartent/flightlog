"""Recent sessions of a repo, for agents (M5 task 2, ADR-0018 "Reading digests").

One read path for `flask sessions`, the MCP tools and the read API: the stored digest plus
what changes after a session (its PR and the PR's outcome), with a goal derived at read time.
"""

import re
import unicodedata

from flightlog.application.ports import DigestQueries
from flightlog.contracts.digest import (
    DigestedSession,
    RecentSession,
    SummaryFilter,
    SummaryPage,
    SummaryState,
)
from flightlog.contracts.sessions import LinkedPullRequest, SessionCursor
from flightlog.domain import AgentSessionStatus

GOAL_LIMIT = 72
_TYPE_PREFIX = re.compile(r"^(?:feat|feature|fix|chore|refactor|docs|test|tests|ci|build|perf)/")


def recent_sessions(repo: str, last: int, queries: DigestQueries) -> list[RecentSession]:
    return [_recent(s) for s in queries.recent(repo, last)]


def attempts_on(repo: str, path: str, last: int, queries: DigestQueries) -> list[RecentSession]:
    """Earlier sessions in the repo whose digest lists this path (relative), newest first."""
    return [_recent(s) for s in queries.attempts_on(repo, path, last)]


def session_summary(session_id: int, queries: DigestQueries) -> RecentSession | None:
    found = queries.one(session_id)
    return _recent(found) if found else None


def summary_page(summary_filter: SummaryFilter, queries: DigestQueries) -> SummaryPage:
    """One page of summaries for the read API (ADR-0020). Keyset-paged, like the sessions."""
    # One row more than the page: if it comes back, there is a next page.
    found = queries.page(summary_filter, summary_filter.limit + 1)
    shown = found[: summary_filter.limit]
    last = shown[-1] if len(found) > summary_filter.limit else None
    return SummaryPage(
        summaries=[_recent(s) for s in shown],
        next_cursor=SessionCursor(last.started_at, last.id) if last else None,
    )


def _recent(session: DigestedSession) -> RecentSession:
    pull_request = max(session.pull_requests, key=lambda p: p.number, default=None)
    if session.digest is not None:
        state = SummaryState.READY
    elif session.status is AgentSessionStatus.ACTIVE:
        state = SummaryState.RUNNING
    else:
        state = SummaryState.PENDING
    return RecentSession(
        id=session.id,
        started_at=session.started_at,
        ended_at=session.ended_at,
        status=session.status,
        branch=clean_text(session.branch, 100) if session.branch else None,
        goal=goal_of(pull_request, session.branch),
        pull_request=pull_request,
        pull_request_title=clean_text(pull_request.title, GOAL_LIMIT) if pull_request else None,
        state=state,
        digest=session.digest,
    )


def goal_of(pull_request: LinkedPullRequest | None, branch: str | None) -> str | None:
    """The PR's title, or the branch made readable: "feat/rate-limits" is "rate limits"."""
    if pull_request is not None:
        return clean_text(pull_request.title, GOAL_LIMIT)
    if branch:
        readable = (
            _TYPE_PREFIX.sub("", branch).replace("/", " ").replace("-", " ").replace("_", " ")
        )
        return clean_text(readable, GOAL_LIMIT)
    return None


def clean_text(text: str, limit: int) -> str:
    """One line of plain text, at most `limit` characters.

    A PR title is written by someone on GitHub, and an agent reads this output: no newlines
    to fake a new entry, no control or format characters (terminal escape sequences, zero-width
    characters). It's still data, not instructions; this only keeps it on its line.
    """
    kept = []
    for ch in text:
        if ch.isspace():
            kept.append(" ")
        elif not unicodedata.category(ch).startswith("C"):  # Cc control, Cf format, …
            kept.append(ch)
    line = " ".join("".join(kept).split())
    return line if len(line) <= limit else line[: limit - 1] + "…"
