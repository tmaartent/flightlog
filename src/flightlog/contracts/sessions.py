import base64
import binascii
import datetime
from dataclasses import dataclass
from enum import StrEnum

from flightlog.domain import AgentSessionStatus


class PullRequestOutcome(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"
    REVERTED = "reverted"  # merged, and later undone by another merged PR


@dataclass(frozen=True)
class LinkedPullRequest:
    """A pull request opened from the branch a session worked on, as the dashboard shows it."""

    number: int
    title: str
    outcome: PullRequestOutcome


@dataclass(frozen=True)
class SessionCursor:
    """Where a page of sessions ends: the next page holds the sessions sorted after this one.

    Sessions are sorted by (started_at, id) descending (ADR-0010). As a token in a URL it is
    opaque: callers pass back what they were given and never build one.
    """

    started_at: datetime.datetime
    id: int

    def to_token(self) -> str:
        raw = f"{self.started_at.isoformat()}|{self.id}".encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def from_token(cls, token: str) -> "SessionCursor":
        """Raises ValueError for anything this class did not produce."""
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
            started_at, session_id = raw.split("|")
            cursor = cls(datetime.datetime.fromisoformat(started_at), int(session_id))
        except (binascii.Error, UnicodeDecodeError, ValueError) as error:
            raise ValueError(f"not a session cursor: {token!r}") from error
        if cursor.started_at.tzinfo is None:
            raise ValueError(f"not a session cursor: {token!r}")
        return cursor


@dataclass(frozen=True)
class SessionFilter:
    """Which sessions to list. None means "any"; `after` is the end of the previous page."""

    repo: str | None = None
    status: AgentSessionStatus | None = None
    after: SessionCursor | None = None
    limit: int = 25


@dataclass(frozen=True)
class SessionSummary:
    """One session as a row in a list: no events, no pull requests."""

    id: int
    source: str
    external_id: str
    repo: str
    branch: str | None
    status: AgentSessionStatus
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    pending_events: int  # events with a job still queued, not yet on the timeline


@dataclass(frozen=True)
class SessionPage:
    sessions: list[SessionSummary]
    next_cursor: SessionCursor | None  # None on the last page
