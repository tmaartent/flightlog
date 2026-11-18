import datetime

from flightlog.application.events import unprocessed_event
from flightlog.application.ports import UnitOfWork
from flightlog.domain import AgentSession


def apply_to_session(event_id: int, now: datetime.datetime, uow: UnitOfWork) -> None:
    """Apply one Claude Code hook event to its agent session, creating the session first.

    Does not commit: the worker owns the transaction, so the event, the session and the
    removal of the job are saved together (ADR-0008). Safe to run twice for the same event,
    because jobs are processed at least once.

    Two workers handling the first events of the same new session can both try to add it;
    the unique constraint on (source, external_id) makes one of them fail, and its retry
    then finds the session.
    """
    event = unprocessed_event(event_id, uow)
    if event is None:
        return

    hook = event.payload.get("hook", {})
    session_id = hook.get("session_id")
    if session_id:
        session = uow.agent_sessions.get(event.source, session_id)
        if session is None:
            session = AgentSession(
                source=event.source,
                external_id=session_id,
                repo=repo_name(hook.get("cwd", "")),
                started_at=event.occurred_at,
            )
            uow.agent_sessions.add(session)
        # Added by the hook client since M3; None for older events and outside a git repo.
        branch = (event.payload.get("git") or {}).get("branch")
        session.record(event.type, event.occurred_at, branch)
        event.agent_session_id = session.id
    event.processed_at = now


def repo_name(cwd: str) -> str:
    """The last folder of the agent's working directory, on Windows and POSIX paths alike.

    Split by hand: os.path on Linux (the worker in Docker) doesn't know backslashes.
    """
    return cwd.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
