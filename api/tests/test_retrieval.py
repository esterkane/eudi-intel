"""Phase 4 unit tests: RRF fusion, tier-aware ordering, citation completeness,
search endpoint (pipeline patched — no model, no infra)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.routers.search as search_router
from app.main import app
from app.services.retrieval import (
    Candidate,
    Citation,
    SearchFilters,
    SearchHit,
    rrf_fuse,
    tier_aware_order,
)


def _candidate(key: str, tier: str) -> Candidate:
    return Candidate(
        key=key,
        content=f"content {key}",
        section_path="A > B",
        citation=Citation(
            doc_title="Doc",
            source_url=f"https://x/{key}",
            tier=tier,
            version_or_tag="main",
            section_heading=key,
            last_seen="2026-06-12T00:00:00+00:00",
        ),
    )


def test_heading_match_bonus_for_exact_section_queries() -> None:
    from app.services.retrieval import heading_match_bonus

    # normalized containment: punctuation/case differences don't matter
    assert heading_match_bonus(
        "Topic 20 - Strong User authentication",
        "A.2.3.13 Topic 20 - Strong User authentication",
    ) == 2.0
    assert heading_match_bonus("topic 20 strong user AUTHENTICATION", "Topic 20 - Strong User authentication") == 2.0
    # prose headings that merely share words get nothing
    assert heading_match_bonus(
        "Topic 20 - Strong User authentication", "4 Current HLRs and Proposals of Changes"
    ) == 0.0
    assert heading_match_bonus("", "anything") == 0.0


def test_rrf_rewards_presence_in_multiple_lists() -> None:
    scores = rrf_fuse([["a", "b", "c"], ["b", "a"], ["b"]])
    assert scores["b"] > scores["a"] > scores["c"]
    # exact RRF arithmetic, k=60
    assert scores["c"] == pytest.approx(1 / 63)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61 + 1 / 61)


def test_tier_breaks_ties_within_score_bucket() -> None:
    scored = [
        (0.83, _candidate("community-hit", "community")),
        (0.81, _candidate("normative-hit", "normative")),  # close → tier wins
        (0.30, _candidate("reference-hit", "reference")),
    ]
    ordered = tier_aware_order(scored)
    assert [c.key for _, c in ordered] == ["normative-hit", "community-hit", "reference-hit"]


def test_clearly_better_score_beats_tier() -> None:
    scored = [
        (0.95, _candidate("community-hit", "community")),
        (0.40, _candidate("normative-hit", "normative")),
    ]
    ordered = tier_aware_order(scored)
    assert ordered[0][1].key == "community-hit"


def test_search_endpoint_returns_full_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_hybrid_search(
        query: str,
        filters: SearchFilters,
        limit: int,
        settings: object,
        embed_text: str | None = None,
    ) -> list[SearchHit]:
        assert filters.tier == "normative"
        candidate = _candidate("k1", "normative")
        return [
            SearchHit(
                score=0.9,
                content=candidate.content,
                section_path=candidate.section_path,
                citation=candidate.citation,
            )
        ]

    monkeypatch.setattr(search_router, "hybrid_search", fake_hybrid_search)
    resp = TestClient(app).get("/search", params={"q": "wallet attestation", "tier": "normative"})
    assert resp.status_code == 200
    body = resp.json()
    citation = body["results"][0]["citation"]
    # citation block contract: every field present (CLAUDE.md)
    assert set(citation) == {
        "doc_title", "source_url", "tier", "version_or_tag", "section_heading", "last_seen",
    }
    assert citation["tier"] == "normative"


def test_search_rejects_bad_tier() -> None:
    resp = TestClient(app).get("/search", params={"q": "x y", "tier": "bogus"})
    assert resp.status_code == 422
