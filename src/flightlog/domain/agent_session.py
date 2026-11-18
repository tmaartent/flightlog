import datetime
from dataclasses import dataclass
from enum import StrEnum

SESSION_END = "SessionEnd"


class AgentSessionStatus(StrEnum):
    ACTIVE = "active"
    STOPPED = "stopped"


@dataclass(eq=False)  # an entity: equal by identity, not by its current values
class AgentSession:
    """
    One coding-agent session, from its first event to its last. The aggregate root.
    """

    source: str
    external_id: str
    repo: str
    started_at: datetime.datetime
    branch: str | None = None
    status: AgentSessionStatus = AgentSessionStatus.ACTIVE
    ended_at: datetime.datetime | None = None
    branch_seen_at: datetime.datetime | None = None  # when `branch` was last reported
    id: int | None = None  # assigned by persistence

    def record(
        self, event_type: str, occurred_at: datetime.datetime, branch: str | None = None
    ) -> None:
        """Apply one event to this session. Safe to call twice with the same event.

        The branch of the latest event wins: the agent may switch branches mid-session, and
        the branch it ends on is the one its PR is opened from.
        """
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if occurred_at < self.started_at:
            self.started_at = occurred_at
        if event_type == SESSION_END:
            if self.ended_at is None or occurred_at > self.ended_at:
                self.ended_at = occurred_at
            if self.status == AgentSessionStatus.ACTIVE:
                self.status = AgentSessionStatus.STOPPED

        if branch is not None and (
            self.branch_seen_at is None or occurred_at > self.branch_seen_at
        ):
            self.branch = branch
            self.branch_seen_at = occurred_at
