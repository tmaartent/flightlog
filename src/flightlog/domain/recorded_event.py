import datetime
from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)  # an entity: equal by identity
class RecordedEvent:
    """Something that happened in a source (GitHub, Claude Code), as it was received.

    A fact: once recorded it is never changed. delivery_id is unique per source, which is
    what makes ingesting the same delivery twice harmless (ADR-0004).
    """

    source: str
    delivery_id: str
    type: str
    occurred_at: datetime.datetime  # from the event itself; decides the order
    payload: dict[str, Any]
    processed_at: datetime.datetime | None = None
    id: int | None = None  # assigned by persistence
