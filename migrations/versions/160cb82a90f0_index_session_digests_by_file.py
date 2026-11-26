"""index session digests by file

Revision ID: 160cb82a90f0
Revises: 0de4520ce9f3
Create Date: 2026-11-26 22:40:32.020124

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "160cb82a90f0"
down_revision: str | Sequence[str] | None = "0de4520ce9f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """GIN index for attempts_on(path): files_touched @> '["src/a.py"]' (ADR-0019)."""
    op.create_index(
        "ix_session_digests_files_touched",
        "session_digests",
        ["files_touched"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"files_touched": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_digests_files_touched",
        table_name="session_digests",
        postgresql_using="gin",
        postgresql_ops={"files_touched": "jsonb_path_ops"},
    )
