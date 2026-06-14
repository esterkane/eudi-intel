"""entity_summaries table (Phase S2 — structured summaries)

Revision ID: 0007_entity_summaries
Revises: 0006_generated_drafts
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_entity_summaries"
down_revision: str | None = "0006_generated_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_url", sa.String(length=1024), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.UniqueConstraint("entity_url", name="uq_entity_summary_url"),
    )


def downgrade() -> None:
    op.drop_table("entity_summaries")
