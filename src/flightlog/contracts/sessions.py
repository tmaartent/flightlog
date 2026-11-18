from dataclasses import dataclass
from enum import StrEnum


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
