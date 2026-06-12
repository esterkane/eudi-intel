"""Tier rules: Annex 2 + ARF tech specs normative, discussions community,
STS never normative (eudi-source-registry skill)."""

from __future__ import annotations

from app.models.source import Tier
from app.parsers.tiering import tier_for_repo_file


def test_arf_annex_2_is_normative() -> None:
    assert (
        tier_for_repo_file("arf_repo", "docs/annexes/annex-2/annex-2.01-high-level-requirements.md")
        == Tier.normative
    )


def test_arf_technical_specs_are_normative() -> None:
    assert tier_for_repo_file("arf_repo", "docs/technical-specifications/ts1.md") == Tier.normative


def test_arf_other_annexes_are_reference() -> None:
    assert tier_for_repo_file("arf_repo", "docs/annexes/annex-1/annex-1.md") == Tier.reference
    assert (
        tier_for_repo_file("arf_repo", "docs/architecture-and-reference-framework-main.md")
        == Tier.reference
    )


def test_arf_discussion_topics_are_community() -> None:
    assert (
        tier_for_repo_file("arf_repo", "docs/discussion-topics/a-privacy-risks.md")
        == Tier.community
    )


def test_sts_is_roadmap_never_normative() -> None:
    assert tier_for_repo_file("sts_repo", "docs/technical-specifications/spec.md") == Tier.roadmap
