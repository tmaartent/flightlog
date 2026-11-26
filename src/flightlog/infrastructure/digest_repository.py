from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from flightlog.contracts.digest import DigestEvent, SessionDigest
from flightlog.domain import AgentSessionStatus
from flightlog.infrastructure.tables import agent_sessions, event_logs, session_digests


class SqlDigestRepository:
    """DigestRepository on PostgreSQL (ADR-0018)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def session(self, agent_session_id: int):
        s = agent_sessions
        row = self._session.execute(
            select(s.c.started_at, s.c.ended_at).where(s.c.id == agent_session_id)
        ).one_or_none()
        return (row.started_at, row.ended_at) if row else None

    def source_events(self, agent_session_id: int) -> list[DigestEvent]:
        # Only these JSON fields are ever read: no content, no URL, no tool_response.
        hook = event_logs.c.payload["hook"]
        tool_input = hook["tool_input"]
        statement = (
            select(
                event_logs.c.id,
                event_logs.c.type,
                event_logs.c.occurred_at,
                hook["tool_name"].astext.label("tool_name"),
                func.coalesce(
                    tool_input["file_path"].astext, tool_input["notebook_path"].astext
                ).label("file_path"),
                tool_input["command"].astext.label("command"),
                hook["cwd"].astext.label("cwd"),
            )
            .where(event_logs.c.agent_session_id == agent_session_id)
            .order_by(event_logs.c.occurred_at, event_logs.c.id)
        )
        return [
            DigestEvent(
                id=row.id,
                type=row.type,
                occurred_at=row.occurred_at,
                tool_name=row.tool_name,
                file_path=row.file_path,
                command=row.command,
                cwd=row.cwd,
            )
            for row in self._session.execute(statement)
        ]

    def save(self, digest: SessionDigest) -> None:
        values = {
            "agent_session_id": digest.agent_session_id,
            "files_touched": digest.files_touched,
            "files_outside_repo": digest.files_outside_repo,
            "edits": digest.edits,
            "test_runs": digest.test_runs,
            "tool_calls": digest.tool_calls,
            "tools": digest.tools,
            "duration_seconds": digest.duration_seconds,
            "event_count": digest.event_count,
            "rules_version": digest.rules_version,
        }
        statement = insert(session_digests).values(**values)
        stored, new = session_digests.c, statement.excluded
        # Two jobs for one session can run at once. Events are never deleted, so the digest
        # computed from more events (or by newer rules) is the newer one: an older one that
        # finishes last must not overwrite it (a lost update). One statement, no race.
        statement = statement.on_conflict_do_update(
            index_elements=[stored.agent_session_id],
            set_={
                **{k: new[k] for k in values if k != "agent_session_id"},
                "computed_at": func.now(),
            },
            where=tuple_(new.rules_version, new.event_count)
            >= tuple_(stored.rules_version, stored.event_count),
        )
        self._session.execute(statement)

    def stale_sessions(self, rules_version: int) -> list[int]:
        s, d = agent_sessions, session_digests
        statement = (
            select(func.max(event_logs.c.id))
            .select_from(s)
            .join(event_logs, event_logs.c.agent_session_id == s.c.id)
            .outerjoin(d, d.c.agent_session_id == s.c.id)
            .where(
                s.c.status == AgentSessionStatus.STOPPED,
                or_(d.c.rules_version.is_(None), d.c.rules_version < rules_version),
            )
            .group_by(s.c.id)
            .order_by(s.c.id)
        )
        return list(self._session.scalars(statement))
