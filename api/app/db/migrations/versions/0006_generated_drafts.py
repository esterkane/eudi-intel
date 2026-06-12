"""generated_drafts table (Phase 7 — authoring plane)

Revision ID: 0006_generated_drafts
Revises: 0005_search_indexes
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_generated_drafts"
down_revision: str | None = "0005_search_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generated_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("source_basis", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("generated_drafts")
