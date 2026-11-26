"""The database schema. Alembic's autogenerate compares against `metadata`."""

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

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
