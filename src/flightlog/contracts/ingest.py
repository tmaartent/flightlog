import datetime
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CLAUDE = "claude"
GITHUB = "github"


@dataclass(frozen=True)
class IngestEvent:
    """Command: record an event a source delivered. Built by the API from a verified request."""

    source: str
    delivery_id: str
    type: str
    occurred_at: datetime.datetime
    payload: dict[str, Any]


class IngestOutcome(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"  # a call to Flightlog's own MCP tools (ADR-0019)


@dataclass(frozen=True)
class IngestResult:
    outcome: IngestOutcome
    event_id: int | None  # None for a duplicate or an ignored event
