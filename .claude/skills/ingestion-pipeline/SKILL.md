---
name: ingestion-pipeline
description: How the ingestion plane works end to end — collectors (git/feed/crawl/scrape), parsing and heading-aware chunking, tiering, snapshot/diff, embedding and dual-index writes, and idempotency rules. Load this when building or debugging any collector, parser, or indexing task.
---

# Ingestion Pipeline

Ingestion is decoupled from query and runs in Celery workers. Flow:
`collect → snapshot → parse → chunk → tier → diff → embed → index`.

## 1. Collectors (token-free; see eudi-source-registry + CLAUDE.md GitHub policy)
- **git collector** — `git clone --depth 1` then `git fetch`/`pull` each repo into a local mirror
  dir. The document corpus (ARF main, annexes, specs, roadmap markdown, changelogs) comes from
  files here — NOT the REST API. No rate limit.
- **feed collector** — fetch `releases.atom`, `tags.atom`, `commits/{branch}.atom` per repo.
  These are outside the REST 60/hr bucket. Source of releases + new-tag detection + commit activity.
- **web collector** — httpx GET + Trafilatura extraction for static MkDocs pages (eudi.dev,
  docs.eudi.dev, conformance.eudi.dev) and the EC page. Use Playwright ONLY when a page needs JS.
- **scrape collector** — fetch issue/PR/discussion list pages as HTML and extract rows
  (title, number, state, updated_at, url). This is the dashboard "activity" source in token-free mode.
- **github_api collector (optional)** — only instantiated if `GITHUB_TOKEN` is set. Then use
  authenticated REST (5000/hr) + ETag conditional requests for issues/PRs/discussions. Build it
  as a strategy that the scrape collector defers to when a token exists. Default: token absent.

Hard rule: in token-free mode do not call `api.github.com` beyond a tiny emergency budget
(≤ ~30/hr). The 60/hr unauthenticated limit is per-IP and ETag 304s still count when unauthenticated.

## 2. Snapshot
Every fetch writes a `SourceSnapshot`: `{source_id, url, fetched_at, content_hash, raw_ref}`.
Snapshots are the audit trail and the input to diffing. Store raw payload (file/blob/db) keyed by hash.

## 3. Parse
- Markdown → parse directly (preserve heading hierarchy).
- HTML → Trafilatura (keep main content + headings).
- PDF/DOCX/PPTX → Docling (background only; rich structure, tables, layout, provenance). Prefer
  the HTML/markdown form of a doc when both exist; only Docling a PDF when no better source.

## 4. Chunk (heading-aware)
- Split on heading boundaries so each chunk = a real **Section** with a stable anchor/URL for
  deep-linking. Keep section path (H1>H2>H3) on the chunk.
- Respect BGE-M3's 8192-token ceiling; target chunks well under that (e.g. 512–1024 tokens) with
  small overlap. Carry: `doc_id, section_path, anchor_url, tier, version_or_tag, source_url`.

## 5. Tier
Assign authority tier from the source rule (eudi-source-registry). Propagate tier to Section and
to every Qdrant payload. Annex 2 + specs = normative; never let community content claim normative.

## 6. Diff / snapshot-versioning
- On a new ARF tag/release (from the feed collector), re-ingest that version and compute a diff
  vs the previous version (section added/removed/changed). Store as a Version/Release diff for the
  "what changed" dashboard and for version-comparison queries.
- Maintain both indexes: **latest-only** (operational) and **history** (per-version).

## 7. Embed + index
- BGE-M3 on CPU (FastEmbed/ONNX) produces **dense + sparse** vectors per chunk, in batches, in the
  worker. Write to Qdrant with full payload (tier, version, repo, section_path, anchor_url,
  last_seen, source_url). Latest chunks → latest collection; versioned chunks → history collection.
- Embedding is the heavy step — always a background Celery task, never inline in a request.

## Idempotency (must-haves)
- Dedupe Documents by `source_url + content_hash`. Re-running a collector must not create duplicates.
- Upserts keyed by stable IDs (e.g. `sha1(source_url)` for docs, `repo#number` for issues/PRs).
- Re-embedding only when `content_hash` changed.
- A failed task is safe to retry: snapshots and upserts are the source of truth, not in-memory state.

## Entities to populate
Document, Section, Version/Tag, Release, Issue, Discussion, PullRequest, Milestone, RoadmapItem
(with maturity state: completed/in-progress/planned), SourceSnapshot. Vectors + payload in Qdrant.
