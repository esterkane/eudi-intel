---
name: semantic-recall
description: Making vague, keyword-uncertain support queries retrieve the right material — a domain glossary/alias map plus LLM query expansion (HyDE-lite) feeding the existing hybrid pipeline. Load this when building query expansion, the glossary, or the recall eval.
---

# Semantic Recall & Query Expansion

A support lead often does not know the exact term. "Android without Google" must find content about
**de-Googled / GMS-less builds, AOSP, GrapheneOS, Play Integrity alternatives** even though none of
those words appear in the query. The hybrid pipeline (hybrid-search skill) is strong on exact
identifiers; this skill strengthens the *recall* end for fuzzy intent.

## Two complementary mechanisms

### 1. Domain glossary / alias map (data, deterministic, fast)
A curated map of EUDI / eIDAS 2.0 terms → definition + aliases, e.g.:
- "android without google" / "de-Googled" / "GMS-less" ↔ AOSP, GrapheneOS, Play Integrity, key attestation
- WUA ↔ Wallet Unit Attestation; PID ↔ Person Identification Data; rQES ↔ remote Qualified e-Signature
- OID4VP / OID4VCI, SD-JWT VC, mso_mdoc, LoA, RP (relying party / verifier), ASWG, ARF, Annex 2
Used two ways: (a) expand a query with matched aliases before retrieval; (b) surface the matched
glossary definitions in the support console so the term can be explained.

### 2. LLM query expansion (HyDE-lite)
For a vague query, `qwen3:8b` produces a short **hypothetical answer paragraph** + a handful of
likely technical terms. We embed the hypothetical (dense recall improves when the query looks like
the target text) and add the terms to the lexical channel. Keep it cheap: one short generation,
cached by normalized query.

## How it plugs in (does NOT replace hybrid search)
- Expanded query = original + alias terms + HyDE terms. Lexical/sparse channels get the terms; the
  dense channel gets the embedding of (query + HyDE paragraph). RRF + rerank are unchanged.
- The **original** query still runs too; expansion only *adds* candidates. Exact-identifier queries
  must not regress — the heading/lexical channels and the exact-match bonus still dominate when the
  query is precise.

## Recall eval (the gate's backbone)
Maintain `tests/eval/recall.jsonl`: vague query → expected source substring(s). Include:
- "android os without google" → de-Googled / AOSP / GrapheneOS / attestation content
- "verifier rejects my request" → OID4VP / relying party / invalid_request material
- "prove the wallet is genuine" → Wallet Unit Attestation
Track **recall@10** (expected source appears in the top 10) with vs. without expansion, and confirm a
set of exact-identifier queries keep ranking their target first (no regression).

## Gate (Phase S3)
The recall eval meets its recall@10 threshold with expansion on (and beats expansion-off on the vague
set), while exact-keyword queries still rank their target first.
