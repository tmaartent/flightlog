import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, MetaData, UniqueConstraint, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class AgentSessionStatus(StrEnum):
    ACTIVE = "active"
    STOPPED = "stopped"
    LINKED = "linked"


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (UniqueConstraint("source", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str]
    external_id: Mapped[str]
    repo: Mapped[str]
    branch: Mapped[str | None]
    status: Mapped[AgentSessionStatus] = mapped_column(
        SQLEnum(
            AgentSessionStatus,
            native_enum=False,
            values_callable=lambda v: [m.value for m in v],
            length=20,
        ),
        default=AgentSessionStatus.ACTIVE,
        nullable=False,
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.UTC)
    )
    ended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class EventLog(Base):
    __tablename__ = "event_logs"
    __table_args__ = (UniqueConstraint("source", "delivery_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str]
    delivery_id: Mapped[str]
    type: Mapped[str]
    # No default: the time comes from the event itself and decides the order (ADR-0004).
    occurred_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    processed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
