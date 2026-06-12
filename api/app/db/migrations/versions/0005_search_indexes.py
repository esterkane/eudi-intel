"""pg_trgm + FTS indexes (Phase 4 — hybrid search query plane)

Revision ID: 0005_search_indexes
Revises: 0004_embedded_hash
Create Date: 2026-06-12
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_search_indexes"
down_revision: str | None = "0004_embedded_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Suggest dictionary columns (hybrid-search skill): doc titles, section
# headings, issue/release/roadmap titles.
_TRGM_INDEXES = (
    ("ix_trgm_documents_title", "documents", "title"),
    ("ix_trgm_sections_heading", "sections", "heading"),
    ("ix_trgm_issues_title", "issues", "title"),
    ("ix_trgm_releases_title", "releases", "title"),
    ("ix_trgm_roadmap_title", "roadmap_items", "title"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_fts_sections ON sections USING GIN "
        "(to_tsvector('english', heading || ' ' || content))"
    )
    for name, table, column in _TRGM_INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} USING GIN ({column} gin_trgm_ops)")


def downgrade() -> None:
    for name, _table, _column in _TRGM_INDEXES:
        op.execute(f"DROP INDEX {name}")
    op.execute("DROP INDEX ix_fts_sections")
