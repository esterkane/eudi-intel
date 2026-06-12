"""source_snapshots table (Phase 1 — collectors)

Revision ID: 0002_source_snapshots
Revises: 0001_baseline
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_source_snapshots"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("payload_ref", sa.String(length=512), nullable=True),
        sa.Column("etag", sa.String(length=128), nullable=True),
        sa.UniqueConstraint("url", "content_hash", name="uq_snapshot_url_hash"),
    )
    op.create_index(
        "ix_source_snapshots_source_id", "source_snapshots", ["source_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_snapshots_source_id", table_name="source_snapshots")
    op.drop_table("source_snapshots")
