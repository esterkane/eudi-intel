"""Phase 5 grounding eval harness (run-and-test skill).

Hits the FULL live stack (api + Qdrant + Postgres + host Ollama with qwen3:8b)
through POST /answer, so it only runs when RUN_GROUNDING_EVAL=1 is set — it is
the Phase 5 gate, not a unit test. Tracks citation-precision (valid markers /
all markers) and refusal-correctness.

Per case:
- answerable: no refusal, ≥1 citation, all citations from real retrieved
  evidence (enforced by construction; double-checked against the evidence
  list), expected source substring present, expected key terms in the answer.
- unanswerable: explicit refusal, zero citations, no invented source.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

API = "http://localhost:8000"
CASES = [
    json.loads(line)
    for line in (Path(__file__).parent / "eval" / "grounding.jsonl").read_text().splitlines()
    if line.strip()
]

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GROUNDING_EVAL") != "1",
    reason="grounding eval is the live Phase 5 gate; set RUN_GROUNDING_EVAL=1",
)

_results: list[dict[str, Any]] = []


def _ask(query: str) -> dict[str, Any]:
    resp = httpx.post(f"{API}/answer", json={"query": query}, timeout=600.0)
    resp.raise_for_status()
    return resp.json()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_grounding_case(case: dict[str, Any]) -> None:
    body = _ask(case["query"])
    total_markers = len(body["cited_indices"]) + len(body["invalid_markers"])
    precision = len(body["cited_indices"]) / total_markers if total_markers else None
    _results.append(
        {
            "id": case["id"],
            "answerable": case["answerable"],
            "refused": body["insufficient_evidence"],
            "citations": len(body["citations"]),
            "invalid_markers": body["invalid_markers"],
            "citation_precision": precision,
        }
    )

    if not case["answerable"]:
        assert body["insufficient_evidence"] is True, (
            f"expected refusal, got: {body['answer'][:200]}"
        )
        assert body["citations"] == [], "refusal must not carry citations"
        return

    assert body["insufficient_evidence"] is False, (
        f"expected an answer, got refusal; evidence count={len(body['evidence'])}"
    )
    assert body["citations"], "answerable case must cite evidence"
    # every citation must correspond to retrieved evidence (re-check the
    # by-construction guarantee end-to-end)
    evidence_urls = {e["citation"]["source_url"] for e in body["evidence"]}
    for citation in body["citations"]:
        assert citation["source_url"] in evidence_urls
        assert citation["tier"] and citation["last_seen"]
    assert any(
        case["expect_source_contains"] in c["source_url"] for c in body["citations"]
    ), f"no citation matches '{case['expect_source_contains']}': " + str(
        [c["source_url"] for c in body["citations"]]
    )
    answer_lower = body["answer"].lower()
    for term in case["expect_answer_mentions"]:
        assert term in answer_lower, f"answer does not mention '{term}'"


def teardown_module() -> None:
    if not _results:
        return
    refusals_correct = sum(
        1 for r in _results if r["refused"] == (not r["answerable"])
    )
    precisions = [r["citation_precision"] for r in _results if r["citation_precision"] is not None]
    print("\n=== grounding eval summary ===")
    for r in _results:
        print(
            f"  {r['id']:<20} refused={r['refused']!s:<5} citations={r['citations']} "
            f"invalid={r['invalid_markers']} precision={r['citation_precision']}"
        )
    print(f"refusal-correctness: {refusals_correct}/{len(_results)}")
    if precisions:
        print(f"mean citation-precision: {sum(precisions) / len(precisions):.3f}")
