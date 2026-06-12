"""First-class entities. Importing this package registers their metadata on Base
so Alembic autogenerate and the app see the same schema.

Phase 1: SourceSnapshot. Phase 2: Document, Section, Version, Release, Issue,
Discussion, PullRequest, Milestone, RoadmapItem, VersionDiff. Phase 7 adds
GeneratedDraft.
"""

from app.models.entities import (
    Discussion,
    Document,
    Issue,
    Maturity,
    Milestone,
    PullRequest,
    Release,
    RoadmapItem,
    Section,
    Version,
    VersionDiff,
)
from app.models.source import FetchMethod, SourceSnapshot, Tier

__all__ = [
    "Discussion",
    "Document",
    "FetchMethod",
    "Issue",
    "Maturity",
    "Milestone",
    "PullRequest",
    "Release",
    "RoadmapItem",
    "Section",
    "SourceSnapshot",
    "Tier",
    "Version",
    "VersionDiff",
]
