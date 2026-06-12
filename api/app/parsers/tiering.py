"""Authority-tier assignment per source rule (eudi-source-registry skill).

Source-level tiers come from the registry; repo files are tiered by path:
Annex 2 and the ARF's formal technical specifications are NORMATIVE, discussion
topics are COMMUNITY, the rest of the ARF docs are REFERENCE. STS content is
explicitly informational ("never normative") → ROADMAP tier.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from app.models.source import Tier

_ARF_NORMATIVE_DIRS = ("docs/annexes/annex-2", "docs/technical-specifications")
_ARF_COMMUNITY_DIRS = ("docs/discussion-topics",)


def tier_for_repo_file(source_id: str, relpath: str) -> Tier:
    path = str(PurePosixPath(relpath))
    if source_id == "arf_repo":
        if any(path.startswith(prefix) for prefix in _ARF_NORMATIVE_DIRS):
            return Tier.normative
        if any(path.startswith(prefix) for prefix in _ARF_COMMUNITY_DIRS):
            return Tier.community
        return Tier.reference
    if source_id == "sts_repo":
        return Tier.roadmap
    return Tier.reference
