"""add agent_sessions.branch_seen_at

Revision ID: f0a5510a1c13
Revises: 995c9a56b1aa
Create Date: 2026-11-16 13:48:12.146283

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0a5510a1c13"
down_revision: str | Sequence[str] | None = "995c9a56b1aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_sessions", sa.Column("branch_seen_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_sessions", "branch_seen_at")
