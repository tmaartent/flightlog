"""create session_digests

Revision ID: 0de4520ce9f3
Revises: 8fba016aa79c
Create Date: 2026-11-26 22:22:34.988426

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0de4520ce9f3"
down_revision: str | Sequence[str] | None = "8fba016aa79c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Stored session summaries (ADR-0018). Empty at first: `flask summaries rebuild` fills it."""
    op.create_table(
        "session_digests",
        sa.Column("agent_session_id", sa.Integer(), nullable=False),
        sa.Column("files_touched", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("files_outside_repo", sa.Integer(), nullable=False),
        sa.Column("edits", sa.Integer(), nullable=False),
        sa.Column("test_runs", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("tools", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_session_digests_agent_session_id_agent_sessions"),
        ),
        sa.PrimaryKeyConstraint("agent_session_id", name=op.f("pk_session_digests")),
    )


def downgrade() -> None:
    op.drop_table("session_digests")
