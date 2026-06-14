"""Phase S4 tests: triage packet assembly (search/answer/playbook patched) and
the related-activity filter that keeps only issue/PR/discussion items."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.services.support as support
from app.main import app
from app.services.generation import GroundedAnswer
from app.services.retrieval import Citation, SearchFilters, SearchHit


def _hit(url: str, title: str, score: float, tier: str = "community") -> SearchHit:
    return SearchHit(
        score=score,
        content="body",
        section_path="A",
        citation=Citation(
            doc_title=title, source_url=url, tier=tier, version_or_tag=None,
            section_heading="(introduction)", last_seen="2026-06-12T00:00:00+00:00",
        ),
    )


REPO = "https://github.com/eu-digital-identity-wallet/eudi-doc-architecture-and-reference-framework"


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"summaries": {}}

    async def fake_search(
        query: str, filters: SearchFilters, limit: int, settings: Any,
        embed_text: str | None = None, rerank_limit: int | None = None,
    ) -> list[SearchHit]:
        return [
            _hit(f"{REPO}/issues/705", "Liveness tests", 0.9),
            _hit(f"{REPO}/issues/705#comment", "Liveness tests", 0.7),  # dup base
            _hit(f"{REPO}/discussions/704", "Liveness discussion", 0.8),
            _hit(f"{REPO}/blob/main/docs/annexes/annex-2/x.md#hlr", "Annex 2", 0.95, "normative"),
        ]

    async def fake_answer(query: str, filters: SearchFilters, settings: Any) -> GroundedAnswer:
        return GroundedAnswer(
            query=query, answer="Grounded [1].", insufficient_evidence=False,
            citations=[_hit(f"{REPO}/issues/705", "t", 1.0).citation],
            cited_indices=[1], invalid_markers=[], evidence=[], evidence_trimmed=False,
        )

    async def fake_summaries(session: Any, urls: list[str]) -> dict[str, dict[str, object]]:
        return {u: {"tl_dr": "x", "category": "bug", "recommended_action": "do y"} for u in urls}

    async def fake_playbook(query: str) -> None:
        return None

    monkeypatch.setattr(support, "hybrid_search", fake_search)
    monkeypatch.setattr(support, "answer_query", fake_answer)
    monkeypatch.setattr(support, "summaries_for_urls", fake_summaries)
    monkeypatch.setattr(support, "best_playbook", fake_playbook)
    return state


def test_triage_packet_full(patched: dict[str, Any]) -> None:
    resp = TestClient(app).post(
        "/support/triage", json={"query": "verifier rejects my presentation", "generate": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    # answer present and cited
    assert body["answer"]["insufficient_evidence"] is False
    assert body["answer"]["citations"]
    # related: only issue/discussion items, deduped by base url, with summaries;
    # the normative annex doc is excluded (not an activity item)
    urls = [r["url"] for r in body["related"]]
    assert f"{REPO}/issues/705" in urls
    assert f"{REPO}/discussions/704" in urls
    assert all("/annexes/" not in u for u in urls)
    assert len(urls) == len(set(urls))  # deduped
    assert all(r["summary"] for r in body["related"])
    # glossary detected the verifier/OID4VP terms
    assert any(g["term"].startswith("OpenID4VP") for g in body["glossary"])


def test_triage_fast_path_skips_generation(patched: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    async def explode(query: str, filters: SearchFilters, settings: Any) -> GroundedAnswer:
        raise AssertionError("generate=False must not call the LLM")

    monkeypatch.setattr(support, "answer_query", explode)
    body = TestClient(app).post(
        "/support/triage", json={"query": "wallet unit attestation", "generate": False}
    ).json()
    assert body["answer"] is None
    assert body["related"]  # retrieval still runs
