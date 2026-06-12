---
name: hybrid-search
description: The query plane — lexical (Postgres FTS) + fuzzy (pg_trgm) + dense/sparse (Qdrant) retrieval, RRF fusion, CPU reranking, citation-block assembly, and autosuggest. Load this when building search endpoints, the retrieval service, autosuggest, or citation rendering.
---

# Hybrid Search & Grounding

EUDI content mixes exact identifiers (standards numbers, section names, version tags, issue
titles) with long conceptual prose. So search is hybrid by design — never vector-only.

## Pipeline (every query)
1. **Lexical** — Postgres full-text search (`tsvector`/`tsquery`, ranked with `ts_rank`) over
   titles, headings, and chunk text. Best for exact identifiers, spec numbers, section names, tags.
2. **Fuzzy / typeahead** — `pg_trgm` similarity for typo-tolerant matching (and autosuggest below).
3. **Semantic / hybrid** — Qdrant **dense + sparse** (both from BGE-M3) with payload filters:
   `tier`, `version_or_tag`, `repo`, `section_path`. Filters let the UI scope to e.g. normative + latest.
4. **Fuse** — **Reciprocal Rank Fusion (RRF)** across the lexical, dense, and sparse result lists.
   RRF score = Σ 1/(k + rank_i), k≈60. Robust without tuning weights.
5. **Rerank** — bge-reranker-v2-m3 (CPU) over the top `RERANK_CANDIDATES` (~30) fused results.
6. **Tier-aware ordering** — when scores are close, prefer higher authority tier (normative >
   reference > roadmap > community). Never let a discussion chunk outrank an Annex 2 chunk on a
   normative question.

## Citation block (assemble for every result cluster)
Each answer/result carries `citations[]`, one object per claim cluster:
```json
{
  "doc_title": "ARF Annex 2 — High-Level Requirements",
  "source_url": "https://eudi.dev/latest/.../annex-2#section-anchor",
  "tier": "normative",
  "version_or_tag": "v2.9.0",
  "section_heading": "Trust model",
  "last_seen": "2026-06-10T08:00:00Z"
}
```
Rules:
- Deep-link to **section anchors** for versioned docs.
- For GitHub-derived facts, the `source_url` is the issue/PR/discussion/release URL directly.
- Always include `tier`, `version_or_tag`, and `last_seen` so freshness and authority are visible.
- A claim with no supporting retrieved chunk gets NO citation and must not be asserted (see grounded-authoring + Phase 5).

## Autosuggest (pg_trgm, local)
Build a suggestion dictionary from: ARF section titles, annex headings, technical-spec titles,
roadmap item titles, issue titles, release titles, repo names, labels, and accepted query logs.
Serve with `pg_trgm` similarity (typo-tolerant) + an FTS exact-prefix path. Update the dictionary
as ingestion adds entities and as users run accepted queries.

## API shape (suggested)
- `GET /search?q=&tier=&version=&repo=&section=` → fused, reranked results + citations.
- `GET /suggest?q=` → ranked title/heading suggestions.
- `POST /answer` → grounded generation over a result set (see grounded-authoring / local-inference).
Return the retrieval set alongside any generated answer so the UI can show evidence + citations.

## Performance notes for the laptop
- Reranking is the main CPU cost; keep candidate count ~30 and make rerank toggleable.
- Embed the query once; reuse for dense+sparse. Cache hot queries in Redis if needed.
- Trim the final evidence passed to the LLM to the 8K context budget BEFORE generation.
