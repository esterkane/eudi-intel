"""Phase S3 recall eval (semantic-recall skill) — the live gate.

Runs against the full stack (RUN_RECALL_EVAL=1). Measures recall@10 on vague
support queries with query expansion ON vs OFF, asserts:
- expansion recall@10 on the answerable vague set meets the threshold and is not
  worse than expansion-off (it should add candidates, never remove the target);
- exact-identifier queries still rank their target #1 with expansion on (no
  regression);
- a query whose target is absent from the corpus ("android without google")
  matches the glossary but returns only low-confidence hits (no fabrication).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

API = "http://localhost:8000"
RECALL_THRESHOLD = 0.8

CASES = [
    json.loads(line)
    for line in (Path(__file__).parent / "eval" / "recall.jsonl").read_text().splitlines()
    if line.strip()
]

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_RECALL_EVAL") != "1",
    reason="recall eval is the live Phase S3 gate; set RUN_RECALL_EVAL=1",
)


def _search(query: str, expand: bool, limit: int = 10) -> dict[str, Any]:
    resp = httpx.get(
        f"{API}/search",
        params={"q": query, "limit": limit, "expand": str(expand).lower()},
        timeout=600.0,
    )
    resp.raise_for_status()
    return resp.json()


def _recall_hit(results: list[dict[str, Any]], expected_any: list[str]) -> bool:
    urls = " ".join(r["citation"]["source_url"].lower() for r in results)
    return any(sub.lower() in urls for sub in expected_any)


def test_recall_eval() -> None:
    answerable = [c for c in CASES if c.get("answerable")]
    hits_on = 0
    hits_off = 0
    rows: list[str] = []
    for case in answerable:
        on = _search(case["query"], expand=True)
        off = _search(case["query"], expand=False)
        hit_on = _recall_hit(on["results"], case["expected_any"])
        hit_off = _recall_hit(off["results"], case["expected_any"])
        hits_on += hit_on
        hits_off += hit_off
        rows.append(f"  {case['id']:<22} expand_on={hit_on!s:<5} expand_off={hit_off!s}")

    recall_on = hits_on / len(answerable)
    recall_off = hits_off / len(answerable)
    print("\n=== recall@10 (answerable vague set) ===")
    print("\n".join(rows))
    print(f"recall_on={recall_on:.2f}  recall_off={recall_off:.2f}  (n={len(answerable)})")

    assert recall_on >= RECALL_THRESHOLD, f"expansion recall {recall_on:.2f} < {RECALL_THRESHOLD}"
    assert recall_on >= recall_off, "expansion must not reduce recall"


def test_exact_queries_do_not_regress() -> None:
    for case in [c for c in CASES if c.get("exact")]:
        results = _search(case["query"], expand=True)["results"]
        assert results, f"{case['id']}: no results"
        top_url = results[0]["citation"]["source_url"].lower()
        assert any(sub in top_url for sub in case["rank1_any"]), (
            f"{case['id']}: exact target not ranked #1 with expansion on (got {top_url})"
        )


def test_absent_topic_matches_glossary_but_stays_low_confidence() -> None:
    case = next(c for c in CASES if c["id"] == "degoogled")
    body = _search(case["query"], expand=True)
    terms = {g["term"] for g in body["glossary"]}
    assert case["glossary_term"] in terms  # glossary explains the term...
    top = body["results"][0]["score"] if body["results"] else 0.0
    # ...but the corpus has no such content, so retrieval stays low-confidence
    # rather than fabricating a strong match.
    assert top < case["max_top_score"], f"unexpected high-confidence hit ({top}) for absent topic"
