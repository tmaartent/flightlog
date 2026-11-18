"""create pull_requests

Revision ID: fb968eed96a6
Revises: f0a5510a1c13
Create Date: 2026-11-16 14:34:53.068223

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fb968eed96a6"
down_revision: str | Sequence[str] | None = "f0a5510a1c13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pull_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "open", "closed", "merged", name="pullrequeststate", native_enum=False, length=20
            ),
            nullable=False,
        ),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reverts", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pull_requests")),
        sa.UniqueConstraint("repo", "number", name=op.f("uq_pull_requests_repo_number")),
    )
    op.create_index("ix_pull_requests_repo_branch", "pull_requests", ["repo", "branch"])
    op.create_index("ix_pull_requests_repo_reverts", "pull_requests", ["repo", "reverts"])


def downgrade() -> None:
    op.drop_index("ix_pull_requests_repo_reverts", table_name="pull_requests")
    op.drop_index("ix_pull_requests_repo_branch", table_name="pull_requests")
    op.drop_table("pull_requests")
