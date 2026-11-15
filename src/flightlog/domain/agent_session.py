import datetime
from dataclasses import dataclass
from enum import StrEnum


class AgentSessionStatus(StrEnum):
    ACTIVE = "active"
    STOPPED = "stopped"
    LINKED = "linked"


@dataclass(eq=False)  # an entity: equal by identity, not by its current values
class AgentSession:
    """One coding-agent session, from its first event to its last. The aggregate root.

    Its rules arrive with the worker (step 4): started_at only moves earlier, ended_at only
    later, and the status only moves forward, so events can be applied in any order.
    """

    source: str
    external_id: str
    repo: str
    started_at: datetime.datetime
    branch: str | None = None
    status: AgentSessionStatus = AgentSessionStatus.ACTIVE
    ended_at: datetime.datetime | None = None
    id: int | None = None  # assigned by persistence
