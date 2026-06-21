"""Offline unit tests for the read-only MCP tools (app/mcp).

No live Postgres / Qdrant: the search service and chunk fetch are injected as
fakes. Covers the success shape (full provenance present), unknown-id business
error, validation errors, and a transient backend error surfaced by `guard`.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.mcp.tools import get_chunk_impl, hybrid_search_impl, list_sources_impl
from app.services.retrieval import Citation, SearchFilters, SearchHit

_CITATION = Citation(
    doc_title="ARF Annex 2",
    source_url="https://eudi.dev/annex-2#topic-20",
    tier="normative",
    version_or_tag="1.5.0",
    section_heading="Topic 20 - Strong User authentication",
    last_seen="2026-06-12T00:00:00+00:00",
)
_HIT = SearchHit(
    score=0.91,
    content="Strong user authentication requires ...",
    section_path="Annex 2 > Topic 20",
    citation=_CITATION,
)

_CITATION_KEYS = {
    "doc_title",
    "source_url",
    "tier",
    "version_or_tag",
    "section_heading",
    "last_seen",
}


# ── hybrid_search ────────────────────────────────────────────────────────────


async def test_hybrid_search_returns_results_with_full_provenance() -> None:
    captured: dict[str, object] = {}

    async def fake_search(
        query: str, filters: SearchFilters, limit: int, settings: object
    ) -> list[SearchHit]:
        captured["query"] = query
        captured["filters"] = filters
        captured["limit"] = limit
        return [_HIT]

    result = await hybrid_search_impl(
        "strong user authentication",
        filters={"tier": "normative"},
        limit=5,
        settings=get_settings(),
        search=fake_search,
    )

    assert "isError" not in result
    assert result["count"] == 1
    citation = result["results"][0]["citation"]
    # provenance contract: the full citation block is preserved (CLAUDE.md)
    assert set(citation) == _CITATION_KEYS
    assert citation["tier"] == "normative"
    assert citation["version_or_tag"] == "1.5.0"
    assert citation["last_seen"] == "2026-06-12T00:00:00+00:00"
    # filters mapped onto the existing SearchFilters model
    assert isinstance(captured["filters"], SearchFilters)
    assert captured["filters"].tier == "normative"  # type: ignore[union-attr]
    assert captured["limit"] == 5


async def test_hybrid_search_empty_query_is_validation_error() -> None:
    async def fake_search(*_a: object, **_k: object) -> list[SearchHit]:
        raise AssertionError("search must not be called on invalid input")

    result = await hybrid_search_impl("   ", settings=get_settings(), search=fake_search)
    assert result["isError"] is True
    assert result["errorCategory"] == "validation"
    assert result["isRetryable"] is False


async def test_hybrid_search_bad_tier_is_validation_error() -> None:
    async def fake_search(*_a: object, **_k: object) -> list[SearchHit]:
        raise AssertionError("search must not be called on invalid input")

    result = await hybrid_search_impl(
        "wallet", filters={"tier": "bogus"}, settings=get_settings(), search=fake_search
    )
    assert result["errorCategory"] == "validation"


async def test_hybrid_search_unknown_filter_key_is_validation_error() -> None:
    async def fake_search(*_a: object, **_k: object) -> list[SearchHit]:
        raise AssertionError("search must not be called on invalid input")

    result = await hybrid_search_impl(
        "wallet", filters={"author": "x"}, settings=get_settings(), search=fake_search
    )
    assert result["errorCategory"] == "validation"


async def test_hybrid_search_out_of_range_limit_is_validation_error() -> None:
    async def fake_search(*_a: object, **_k: object) -> list[SearchHit]:
        raise AssertionError("search must not be called on invalid input")

    result = await hybrid_search_impl(
        "wallet", limit=999, settings=get_settings(), search=fake_search
    )
    assert result["errorCategory"] == "validation"


async def test_hybrid_search_backend_down_is_transient_error() -> None:
    async def boom(*_a: object, **_k: object) -> list[SearchHit]:
        raise httpx.ConnectError("qdrant unreachable")

    result = await hybrid_search_impl("wallet", settings=get_settings(), search=boom)
    assert result["isError"] is True
    assert result["errorCategory"] == "transient"
    assert result["isRetryable"] is True
    # no stack trace / raw error leaks into the message
    assert "Traceback" not in result["message"]


# ── get_chunk ────────────────────────────────────────────────────────────────


async def test_get_chunk_returns_chunk_with_full_provenance() -> None:
    async def fake_fetch(chunk_id: int) -> SearchHit | None:
        assert chunk_id == 42
        return _HIT

    result = await get_chunk_impl(42, fetch=fake_fetch)
    assert "isError" not in result
    assert result["chunk_id"] == 42
    assert set(result["chunk"]["citation"]) == _CITATION_KEYS


async def test_get_chunk_unknown_id_is_business_error() -> None:
    async def fake_fetch(_chunk_id: int) -> SearchHit | None:
        return None

    result = await get_chunk_impl(999, fetch=fake_fetch)
    assert result["isError"] is True
    assert result["errorCategory"] == "business"
    assert result["isRetryable"] is False


async def test_get_chunk_non_positive_id_is_validation_error() -> None:
    async def fake_fetch(_chunk_id: int) -> SearchHit | None:
        raise AssertionError("fetch must not be called on invalid input")

    result = await get_chunk_impl(0, fetch=fake_fetch)
    assert result["errorCategory"] == "validation"


async def test_get_chunk_backend_down_is_transient_error() -> None:
    async def boom(_chunk_id: int) -> SearchHit | None:
        raise httpx.ConnectError("postgres unreachable")

    result = await get_chunk_impl(1, fetch=boom)
    assert result["errorCategory"] == "transient"
    assert result["isRetryable"] is True


# ── list_sources ─────────────────────────────────────────────────────────────


async def test_list_sources_returns_registry_with_tiers() -> None:
    result = await list_sources_impl()
    assert "isError" not in result
    assert result["count"] >= 1
    entry = result["sources"][0]
    assert set(entry) == {"id", "title", "tier", "method", "url"}
    tiers = {s["tier"] for s in result["sources"]}
    # tiers are the authority labels, surfaced so callers can weight sources
    assert tiers <= {"normative", "reference", "roadmap", "community"}
    methods = {s["method"] for s in result["sources"]}
    assert methods <= {"git", "feed", "crawl", "scrape"}


async def test_list_sources_uses_injected_registry() -> None:
    from app.collectors.registry import SourceSpec
    from app.models.source import FetchMethod, Tier

    fake = (
        SourceSpec(id="x", title="X", tier=Tier.normative, method=FetchMethod.git, url="https://x"),
    )
    result = await list_sources_impl(registry=fake)
    assert result["count"] == 1
    assert result["sources"][0]["id"] == "x"
    assert result["sources"][0]["tier"] == "normative"
