from typing import Any

from flightlog.application.jobs import jobs_for
from flightlog.application.ports import UnitOfWork
from flightlog.contracts.ingest import CLAUDE, IngestEvent, IngestOutcome, IngestResult
from flightlog.domain import RecordedEvent

OWN_MCP_TOOLS = "mcp__flightlog__"


def is_own_mcp_call(payload: dict[str, Any]) -> bool:
    """A hook event about one of Flightlog's own MCP tools. The hook script skips those; this
    catches an older script, so Flightlog never records itself (ADR-0019)."""
    hook = payload.get("hook")
    tool_name = hook.get("tool_name") if isinstance(hook, dict) else None
    return isinstance(tool_name, str) and tool_name.startswith(OWN_MCP_TOOLS)


def ingest_event(command: IngestEvent, uow: UnitOfWork) -> IngestResult:
    """Record a delivered event exactly once and queue it for the worker, in one transaction.

    Event and job are committed together: there is no moment where an event exists without
    its job, so no event is ever lost between ingest and processing (ADR-0008).
    """
    if command.source == CLAUDE and is_own_mcp_call(command.payload):
        return IngestResult(IngestOutcome.IGNORED, None)

    event = RecordedEvent(
        source=command.source,
        delivery_id=command.delivery_id,
        type=command.type,
        occurred_at=command.occurred_at,
        payload=command.payload,
    )
    event_id = uow.events.add_if_new(event)
    if event_id is not None:
        for kind in jobs_for(event.source, event.type):
            uow.jobs.enqueue(event_id, kind)
    uow.commit()

    if event_id is None:
        return IngestResult(IngestOutcome.DUPLICATE, None)
    return IngestResult(IngestOutcome.CREATED, event_id)
