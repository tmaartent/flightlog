import datetime
import re
from dataclasses import dataclass
from enum import StrEnum

# GitHub's "Revert" button opens a PR whose body starts with "Reverts owner/repo#123".
_REVERTS = re.compile(r"^Reverts [\w.-]+/[\w.-]+#(\d+)")


class PullRequestState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"  # closed without merging
    MERGED = "merged"


@dataclass(eq=False)  # an entity: equal by identity, not by its current values
class PullRequest:
    """A GitHub pull request as last seen. Its own aggregate: it changes without any session.

    Sessions are linked to it at read time, on (repo, branch) (ADR-0009).
    """

    repo: str
    number: int
    branch: str
    title: str
    updated_at: datetime.datetime  # GitHub's, to put out-of-order deliveries in order
    state: PullRequestState = PullRequestState.OPEN
    merged_at: datetime.datetime | None = None
    reverts: int | None = None  # number of the PR this one reverts, in the same repo; not an FK
    id: int | None = None  # assigned by persistence

    def update(self, seen: "PullRequest") -> None:
        """Apply a later snapshot of this PR. Safe to call twice, and in any order.

        The newest snapshot wins, except that merged is final: GitHub can't reopen a merged PR,
        so an older "open" delivery arriving late must not undo it.
        """
        if seen.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        if (seen.repo, seen.number) != (self.repo, self.number):
            raise ValueError("a snapshot of another pull request")
        if self.state is PullRequestState.MERGED:
            return
        if seen.updated_at < self.updated_at and seen.state is not PullRequestState.MERGED:
            return
        self.title = seen.title
        self.state = seen.state
        self.merged_at = seen.merged_at
        self.reverts = seen.reverts
        self.updated_at = seen.updated_at


def parse_reverts(body: str | None) -> int | None:
    """The number in GitHub's "Reverts owner/repo#123" body, or None."""
    match = _REVERTS.match(body or "")
    return int(match.group(1)) if match else None
