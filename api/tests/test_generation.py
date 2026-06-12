"""Phase 5 unit tests — search and LLM patched, fully offline."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.services.generation as gen
from app.core.config import get_settings
from app.main import app
from app.services.generation import (
    REFUSAL_PHRASE,
    EvidenceBlock,
    build_evidence_blocks,
    is_refusal,
    parse_citations,
    render_prompt,
    trim_to_budget,
)
from app.services.retrieval import Citation, SearchFilters, SearchHit


def _hit(n: int, content: str = "evidence text", tier: str = "normative") -> SearchHit:
    return SearchHit(
        score=1.0,
        content=content,
        section_path="A > B",
        citation=Citation(
            doc_title=f"Doc {n}",
            source_url=f"https://x/doc{n}#s",
            tier=tier,
            version_or_tag="main",
            section_heading=f"Heading {n}",
            last_seen="2026-06-12T00:00:00+00:00",
        ),
    )


def test_select_evidence_reserves_slots_for_authority_tiers() -> None:
    from app.services.generation import select_evidence

    pool = [_hit(i, tier="community") for i in range(1, 10)]
    pool.append(_hit(10, tier="normative"))   # rank 10
    pool.append(_hit(11, tier="reference"))   # rank 11
    selected = select_evidence(pool, 8)
    tiers = [h.citation.tier for h in selected]
    assert "normative" in tiers and "reference" in tiers
    assert len(selected) == 8
    # rank order preserved: community leaders still first
    assert selected[0].citation.doc_title == "Doc 1"


def test_select_evidence_passthrough_when_pool_small() -> None:
    from app.services.generation import select_evidence

    pool = [_hit(1, tier="community")]
    assert select_evidence(pool, 8) == pool


def test_citation_markers_resolve_only_to_real_evidence() -> None:
    blocks = build_evidence_blocks([_hit(1), _hit(2)])
    answer = "Claim one [1]. Claim two [2][7]. Repeat [1]."
    citations, cited, invalid = parse_citations(answer, blocks)
    assert cited == [1, 2]
    assert invalid == [7]  # fabricated marker can never become a citation
    assert [c.doc_title for c in citations] == ["Doc 1", "Doc 2"]


def test_refusal_detection_is_case_insensitive() -> None:
    assert is_refusal("Not supported by sources")
    assert is_refusal("the answer is NOT SUPPORTED BY SOURCES.")
    assert not is_refusal("supported by annex 2 [1]")


def test_trim_keeps_whole_blocks_in_rank_order() -> None:
    settings = get_settings()
    big = "x" * 4000  # ~1000 tokens per block
    blocks = build_evidence_blocks([_hit(i, content=big) for i in range(1, 12)])
    kept, trimmed = trim_to_budget(blocks, settings)
    assert trimmed
    assert 0 < len(kept) < len(blocks)
    assert [b.index for b in kept] == list(range(1, len(kept) + 1))


def test_prompt_carries_tier_and_metadata() -> None:
    prompt = render_prompt("what is X?", build_evidence_blocks([_hit(1)]))
    assert "[1] (tier: normative | doc: Doc 1 | section: Heading 1" in prompt
    assert "QUESTION: what is X?" in prompt


@pytest.fixture
def patched_search(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    state: dict[str, object] = {"hits": [_hit(1), _hit(2)], "llm_answer": ""}

    async def fake_search(
        query: str, filters: SearchFilters, limit: int, settings: object
    ) -> list[SearchHit]:
        return list(state["hits"])  # type: ignore[arg-type]

    async def fake_llm(prompt: str, settings: object) -> str:
        return str(state["llm_answer"])

    monkeypatch.setattr(gen, "hybrid_search", fake_search)
    monkeypatch.setattr(gen, "_call_ollama", fake_llm)
    return state


def test_answer_endpoint_grounded(patched_search: dict[str, object]) -> None:
    patched_search["llm_answer"] = "Wallet attestation requires X [1]. Also Y [2]."
    resp = TestClient(app).post("/answer", json={"query": "wallet attestation?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["insufficient_evidence"] is False
    assert [c["doc_title"] for c in body["citations"]] == ["Doc 1", "Doc 2"]
    assert body["invalid_markers"] == []
    assert len(body["evidence"]) == 2


def test_answer_endpoint_refusal_path(patched_search: dict[str, object]) -> None:
    patched_search["llm_answer"] = "Not supported by sources"
    body = TestClient(app).post("/answer", json={"query": "capital of France?"}).json()
    assert body["insufficient_evidence"] is True
    assert body["citations"] == []
    assert REFUSAL_PHRASE in body["answer"].lower()


def test_uncited_answer_collapses_to_refusal(patched_search: dict[str, object]) -> None:
    patched_search["llm_answer"] = "Confident claim with no markers at all."
    body = TestClient(app).post("/answer", json={"query": "anything?"}).json()
    assert body["insufficient_evidence"] is True
    assert body["citations"] == []


def test_no_evidence_refuses_without_llm_call(
    patched_search: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    patched_search["hits"] = []

    async def explode(prompt: str, settings: object) -> str:
        raise AssertionError("LLM must not be called without evidence")

    monkeypatch.setattr(gen, "_call_ollama", explode)
    body = TestClient(app).post("/answer", json={"query": "anything?"}).json()
    assert body["insufficient_evidence"] is True
    assert body["evidence"] == []


def test_llm_down_returns_503(
    patched_search: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(prompt: str, settings: object) -> str:
        raise gen.LlmUnavailableError("connection refused")

    monkeypatch.setattr(gen, "_call_ollama", down)
    resp = TestClient(app).post("/answer", json={"query": "anything?"})
    assert resp.status_code == 503
    assert "connection refused" in resp.json()["detail"]


def test_evidence_block_typing() -> None:
    block = EvidenceBlock(index=1, citation=_hit(1).citation, content="c")
    assert block.index == 1
