"""create connectors

Revision ID: 3f83215d2351
Revises: 658eb82cdc23
Create Date: 2026-11-26 21:09:43.920106

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f83215d2351"
down_revision: str | Sequence[str] | None = "658eb82cdc23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Clients of the read API, one key each (ADR-0005): only the prefix and a hash."""
    op.create_table(
        "connectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_prefix", sa.String(length=8), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connectors")),
        sa.UniqueConstraint("key_prefix", name=op.f("uq_connectors_key_prefix")),
        sa.UniqueConstraint("name", name=op.f("uq_connectors_name")),
    )


def downgrade() -> None:
    op.drop_table("connectors")
