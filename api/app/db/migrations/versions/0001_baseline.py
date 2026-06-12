"""baseline (empty)

Establishes the Alembic head. Schema entities (Document, Section, Version, ...)
are introduced by migrations in Phase 2.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-11
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Baseline — no schema yet."""


def downgrade() -> None:
    """Baseline — nothing to drop."""
