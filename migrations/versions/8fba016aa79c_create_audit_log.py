"""create audit_log

Revision ID: 8fba016aa79c
Revises: 3f83215d2351
Create Date: 2026-11-26 21:31:32.102130

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8fba016aa79c"
down_revision: str | Sequence[str] | None = "3f83215d2351"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The audit log (ADR-0015): one row per read API call and per admin action."""
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "actor_kind",
            sa.Enum(
                "connector", "admin", "anonymous", name="actorkind", native_enum=False, length=20
            ),
            nullable=False,
        ),
        sa.Column("connector_id", sa.Integer(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("endpoint", sa.String(length=100), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("object_type", sa.String(length=50), nullable=True),
        sa.Column("object_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_id"], ["connectors.id"], name=op.f("fk_audit_log_connector_id_connectors")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_connector_id", "audit_log", ["connector_id", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_log_connector_id", table_name="audit_log")
    op.drop_table("audit_log")
