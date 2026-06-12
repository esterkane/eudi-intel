"""sections.embedded_hash (Phase 3 — re-embed only on content change)

Revision ID: 0004_embedded_hash
Revises: 0003_entities
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_embedded_hash"
down_revision: str | None = "0003_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sections", sa.Column("embedded_hash", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sections", "embedded_hash")
