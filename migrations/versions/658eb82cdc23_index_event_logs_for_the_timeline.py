"""index event_logs for the session timeline

Revision ID: 658eb82cdc23
Revises: fb968eed96a6
Create Date: 2026-11-26 21:00:00.000000

A session's timeline selects its events by agent_session_id, ordered by (occurred_at, id)
(ADR-0010). One composite index serves both the filter and the sort.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "658eb82cdc23"
down_revision: str | Sequence[str] | None = "fb968eed96a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_event_logs_session_timeline",
        "event_logs",
        ["agent_session_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_logs_session_timeline", table_name="event_logs")
