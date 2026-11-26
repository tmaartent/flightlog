import datetime
import re
from dataclasses import dataclass

from flightlog.contracts.sessions import LinkedPullRequest, PullRequestOutcome
from flightlog.domain import AgentSessionStatus

_ISO_WEEK = re.compile(r"(\d{4})-W(\d{2})")


@dataclass(frozen=True, order=True)
class IsoWeek:
    """An ISO 8601 week, Monday 00:00 UTC up to the next Monday (ADR-0016)."""

    year: int
    week: int

    @classmethod
    def parse(cls, text: str) -> "IsoWeek":
        """Parse "2026-W46". Raises ValueError for anything else, a week 54 included."""
        match = _ISO_WEEK.fullmatch(text)
        if match is None:
            raise ValueError(f"not an ISO week like 2026-W46: {text!r}")
        year, week = int(match[1]), int(match[2])
        try:
            datetime.date.fromisocalendar(year, week, 1)
        except ValueError:
            raise ValueError(f"{text} has no week {week}") from None
        return cls(year, week)

    @classmethod
    def last_full_week(cls, today: datetime.date) -> "IsoWeek":
        """The week before the one `today` is in: the latest week that is over."""
        year, week, _ = (today - datetime.timedelta(days=7)).isocalendar()
        return cls(year, week)

    @property
    def start(self) -> datetime.datetime:
        monday = datetime.date.fromisocalendar(self.year, self.week, 1)
        return datetime.datetime.combine(monday, datetime.time(), tzinfo=datetime.UTC)

    @property
    def end(self) -> datetime.datetime:
        """Exclusive: the next Monday at 00:00 UTC."""
        return self.start + datetime.timedelta(days=7)

    def __str__(self) -> str:
        return f"{self.year}-W{self.week:02d}"


@dataclass(frozen=True)
class ReportSession:
    """A session that started in the week, with the PRs linked to it (ADR-0009)."""

    id: int
    repo: str
    branch: str | None
    status: AgentSessionStatus
    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    pull_requests: list[LinkedPullRequest]


@dataclass(frozen=True)
class ReportRow:
    """One line of a repo's session table. Counts and names only, never a command."""

    started_at: datetime.datetime
    ended_at: datetime.datetime | None
    branch: str | None
    edits: int
    test_runs: int
    pull_request: LinkedPullRequest | None  # the newest one, when there are several


@dataclass(frozen=True)
class RepoWeek:
    """Everything on one repo's page."""

    repo: str
    sessions: int
    stopped: int
    active: int
    time_spent: datetime.timedelta  # stopped sessions only: an active one has no end yet
    test_runs: int
    pull_requests: dict[PullRequestOutcome, int]  # distinct PRs, every outcome present
    top_files: list[tuple[str, int]]  # (path, edits), most edited first
    rows: list[ReportRow]  # newest first, at most ROW_LIMIT
    rows_not_shown: int


@dataclass(frozen=True)
class WeeklyReport:
    week: IsoWeek
    generated_at: datetime.datetime
    repos: list[RepoWeek]  # sorted by name; one page each
