"""The database schema. Alembic's autogenerate compares against `metadata`."""

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from flightlog.domain import AgentSessionStatus

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
    UniqueConstraint("source", "delivery_id"),
)
