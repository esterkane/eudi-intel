"""First-class entities. Importing this package registers their metadata on Base
so Alembic autogenerate and the app see the same schema.

Phase 1: SourceSnapshot. Phase 2 adds Document, Section, Version/Tag, Release,
Issue, Discussion, PullRequest, Milestone, RoadmapItem, GeneratedDraft.
"""

from app.models.source import FetchMethod, SourceSnapshot, Tier

__all__ = ["FetchMethod", "SourceSnapshot", "Tier"]
