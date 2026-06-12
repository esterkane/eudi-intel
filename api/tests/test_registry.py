"""Registry invariants: unique ids, https URLs, sane tier/method combinations."""

from __future__ import annotations

from app.collectors.registry import REGISTRY, get_source
from app.models.source import FetchMethod, Tier


def test_ids_unique() -> None:
    ids = [s.id for s in REGISTRY]
    assert len(ids) == len(set(ids))


def test_urls_are_https() -> None:
    assert all(s.url.startswith("https://") for s in REGISTRY)


def test_api_urls_only_on_github_rest(  # token strategy only applies to GitHub sources
) -> None:
    for s in REGISTRY:
        if s.api_url is not None:
            assert s.api_url.startswith("https://api.github.com/")


def test_community_sources_are_scraped_not_normative() -> None:
    for s in REGISTRY:
        if s.method == FetchMethod.scrape:
            assert s.tier == Tier.community
        # No source-level normative tier: Annex 2 is promoted at parse time (Phase 2).
        assert s.tier != Tier.normative


def test_all_methods_covered() -> None:
    methods = {s.method for s in REGISTRY}
    assert methods == {FetchMethod.git, FetchMethod.feed, FetchMethod.crawl, FetchMethod.scrape}


def test_get_source() -> None:
    assert get_source("arf_repo") is not None
    assert get_source("nope") is None
