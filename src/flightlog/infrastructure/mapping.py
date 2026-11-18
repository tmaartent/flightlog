"""Imperative mapping: SQLAlchemy learns about the domain classes; they know nothing about it.

received_at is mapped but deliberately not a field of RecordedEvent: the database fills it,
and leaving it out of the constructor means the INSERT omits it, so the server default applies.
"""

from sqlalchemy.orm import registry

from flightlog.domain import AgentSession, PullRequest, RecordedEvent
from flightlog.infrastructure.tables import agent_sessions, event_logs, metadata, pull_requests

mapper_registry = registry(metadata=metadata)
_started = False


def start_mappers() -> None:
    """Map the domain classes onto the tables. Safe to call more than once."""
    global _started
    if _started:
        return
    mapper_registry.map_imperatively(AgentSession, agent_sessions)
    mapper_registry.map_imperatively(RecordedEvent, event_logs)
    mapper_registry.map_imperatively(PullRequest, pull_requests)
    _started = True
