---
name: entity-summarization
description: Structured, cached, grounded summaries of issues / PRs / discussions / releases so a dashboard card or search result tells you exactly what it is about at a glance. Load this when building the summarization service, the summary schema, or rendering summaries on cards.
---

# Entity Summarization

A support lead scanning the dashboard must see, per card, **exactly what the issue / FR / release is
about** without opening it. A raw title is not enough. Every activity entity carries a structured,
grounded summary, generated once and cached.

## Schema (strict — the model fills this, nothing else)
```json
{
  "tl_dr": "one sentence, plain language",
  "category": "bug | feature_request | question | discussion | release | spec_change | other",
  "components": ["wallet", "verifier", "issuer", "oid4vp", "oid4vci", "..."],
  "what": "what is being reported/changed (2-3 sentences)",
  "why": "why it matters / impact on integrators (1-2 sentences, omit if unknown)",
  "status": "open | closed | merged | published | unknown",
  "recommended_action": "what a support lead should tell a partner / do next (1 sentence)",
  "non_normative": true
}
```
- `non_normative` is **true** for issue/PR/discussion summaries (community tier) and must be honored
  by the UI as a label. Releases are roadmap tier.
- The model must fill fields **only from the entity's ingested content** (S1 body + title + metadata).
  If there is not enough content to summarize, emit `tl_dr: "insufficient detail to summarize"` and
  leave `what`/`why` empty — never invent.

## Generation
- `qwen3:8b`, low temperature, JSON-only output validated against the schema (retry once on invalid
  JSON, then store an `insufficient detail` stub rather than failing the batch).
- Input = the entity's title + ingested body Document/Sections (S1). No outside knowledge.
- Heavy and batched — runs in the **Celery worker**, never on the request path.

## Caching & freshness
- Store the summary + the `content_hash` it was generated from on the entity (or a side table).
- Regenerate only when the entity's content_hash changes (same idempotency rule as embeddings).
- The dashboard and search read the cached summary; a missing summary degrades gracefully to the
  title (the console never blocks waiting for generation).

## Where it shows
- Dashboard cards (issues, releases, roadmap, activity) — tl;dr + category + status + recommended action.
- Search results and the support console's "related activity" list.

## Gate (Phase S2)
Sampled issue/release cards show a structured summary derived from real ingested content; an entity
with no content yields the explicit insufficient-detail stub (never invented); summaries regenerate
when content changes.
