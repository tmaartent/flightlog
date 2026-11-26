"""The database schema. Alembic's autogenerate compares against `metadata`."""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from flightlog.contracts.audit import ActorKind
from flightlog.domain import AgentSessionStatus, PullRequestState

# Predictable constraint names, so later migrations can refer to them.
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

agent_sessions = Table(
    "agent_sessions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String, nullable=False),
    Column("external_id", String, nullable=False),
    Column("repo", String, nullable=False),
    Column("branch", String, nullable=True),
    Column(
        "status",
        Enum(
            AgentSessionStatus,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],  # store "active", not "ACTIVE"
            length=20,
        ),
        nullable=False,
    ),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True), nullable=True),
    Column("branch_seen_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("source", "external_id"),
)

event_logs = Table(
    "event_logs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String, nullable=False),
    Column("delivery_id", String, nullable=False),
    Column("type", String, nullable=False),
    # No default: the time comes from the event itself and decides the order (ADR-0004).
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=True),
    # Set by the worker once the event is applied; until then the event has no session.
    Column("agent_session_id", Integer, ForeignKey("agent_sessions.id"), nullable=True),
    UniqueConstraint("source", "delivery_id"),
    # A session's timeline, in order (ADR-0010). PostgreSQL doesn't index foreign keys itself.
    Index("ix_event_logs_session_timeline", "agent_session_id", "occurred_at", "id"),
)

# The work queue (ADR-0008): one row per job still to do. A finished job is deleted, so a row's
# existence means "pending"; failed_at marks a job that was given up on.
event_jobs = Table(
    "event_jobs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("event_log_id", Integer, ForeignKey("event_logs.id"), nullable=False),
    Column("kind", String(50), nullable=False),
    Column("attempts", Integer, server_default=text("0"), nullable=False),
    Column("available_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("last_error", Text, nullable=True),
    Column("failed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    UniqueConstraint("event_log_id", "kind"),
    Index("ix_event_jobs_available_at", "available_at"),
)

# The latest known state of each pull request. Linked to sessions at read time, on
# (repo, branch); "reverted" is derived from another merged PR whose `reverts` points here.
pull_requests = Table(
    "pull_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repo", String, nullable=False),
    Column("number", Integer, nullable=False),
    Column("branch", String, nullable=False),
    Column("title", String, nullable=False),
    Column(
        "state",
        Enum(
            PullRequestState,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],  # store "merged", not "MERGED"
            length=20,
        ),
        nullable=False,
    ),
    Column("merged_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("reverts", Integer, nullable=True),
    UniqueConstraint("repo", "number"),
    Index("ix_pull_requests_repo_branch", "repo", "branch"),  # session -> its pull requests
    Index("ix_pull_requests_repo_reverts", "repo", "reverts"),  # was this PR reverted?
)

# Clients of the read API, one key each (ADR-0005). Only the key's prefix and its SHA-256 are
# stored. Revoking sets revoked_at and keeps the row, so audit rows can still name it.
connectors = Table(
    "connectors",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("key_prefix", String(8), nullable=False),
    Column("key_hash", String(64), nullable=False),  # hex SHA-256 of the full key
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("name"),
    UniqueConstraint("key_prefix"),  # every request looks a key up by its prefix
)

# One row per read API call and per admin action (ADR-0015). Append-only: the code has no
# UPDATE or DELETE for it. The outcome isn't stored; it is read from `status`.
audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, primary_key=True),  # a flood of 429s is a row each
    Column("occurred_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column(
        "actor_kind",
        Enum(
            ActorKind,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
            length=20,
        ),
        nullable=False,
    ),
    Column("connector_id", Integer, ForeignKey("connectors.id"), nullable=True),
    Column("ip", String(45), nullable=True),  # long enough for IPv6
    Column("method", String(10), nullable=False),
    Column("endpoint", String(100), nullable=True),  # None when no route matched
    Column("path", Text, nullable=False),
    Column("object_type", String(50), nullable=True),
    Column("object_id", String(100), nullable=True),
    Column("status", SmallInteger, nullable=False),
    # The admin page filters on a connector, newest first.
    Index("ix_audit_log_connector_id", "connector_id", "id"),
)

# The stored summary of a finished session (ADR-0018): structured facts only, computed by the
# summarize_session job. The PR outcome isn't here: it changes later, so it's read live.
session_digests = Table(
    "session_digests",
    metadata,
    Column("agent_session_id", Integer, ForeignKey("agent_sessions.id"), primary_key=True),
    Column("files_touched", JSONB, nullable=False),  # paths relative to the repo
    Column("files_outside_repo", Integer, nullable=False),
    Column("edits", Integer, nullable=False),
    Column("test_runs", Integer, nullable=False),
    Column("tool_calls", Integer, nullable=False),
    Column("tools", JSONB, nullable=False),  # {tool name: calls}
    Column("duration_seconds", Integer, nullable=True),
    Column("event_count", Integer, nullable=False),  # the newer digest has more
    Column("rules_version", Integer, nullable=False),
    Column("computed_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    # attempts_on(path): `files_touched @> '["src/a.py"]'`. jsonb_path_ops is smaller and faster
    # than the default GIN opclass, and containment is the only operator used (ADR-0019).
    Index(
        "ix_session_digests_files_touched",
        "files_touched",
        postgresql_using="gin",
        postgresql_ops={"files_touched": "jsonb_path_ops"},
    ),
)
