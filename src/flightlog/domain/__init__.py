"""The domain: what Flightlog is about, in plain Python. No Flask, no SQLAlchemy."""

from flightlog.domain.agent_session import AgentSession, AgentSessionStatus
from flightlog.domain.recorded_event import RecordedEvent

__all__ = ["AgentSession", "AgentSessionStatus", "RecordedEvent"]
