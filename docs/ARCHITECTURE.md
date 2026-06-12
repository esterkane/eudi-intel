# Architecture — EUDI Intelligence & Authoring Workbench

This is the hardware-adapted architecture (RTX 4060 8 GB VRAM / 32 GB RAM, single user,
local Docker). It refines the original design document for this machine. CLAUDE.md holds
the binding rules; this file explains the *why* and the data flow.

## 1. Design principles
- **Grounded RAG, not chat-over-docs.** EUDI material is authoritative *and* fast-moving
  (the ARF is SemVer-released on GitHub; the STS roadmap is explicitly "subject to change";
  the reference-implementation roadmap is a live signal). Freshness and provenance beat
  memorization, so the volatile facts live in retrieval, not in weights.
- **Source-aware and version-aware.** A discussion paper must never outrank the latest
  Annex 2. We carry an authority tier and a version/tag on every chunk.
- **Two planes.** Ingestion (mirror + normalize) is decoupled from query (retrieve + ground
  + author) so daily refresh never blocks interactive use.

## 2. The 8 GB inference plane (the core adaptation)
On an 8 GB card you cannot co-resident the generator, embedder, and reranker on the GPU.
Resolution:

| Model | Role | Placement | Why |
|---|---|---|---|
| `qwen3:8b` Q4_K_M | generation | **GPU (Ollama)** | ~5–6 GB at 8K ctx, fully resident, multilingual |
| BGE-M3 | dense+sparse embeddings | **CPU** | batch at ingest (background); 1 query vector at query time is cheap |
| bge-reranker-v2-m3 | final ranking | **CPU** | only rerank top ~30 candidates; ~1–3 s on CPU is fine |

Context is capped at 8K. Embedding is a Celery background job. This keeps the GPU free for
generation and keeps everything off the system-RAM spill cliff.

## 3. Component map
```
            ┌───────────────────────────────┐
            │            Next.js UI          │
            │  dashboard • search • drafts   │
            └───────────────┬───────────────┘
                            │ REST
            ┌───────────────▼───────────────┐
            │            FastAPI             │
            │ query planning • RRF • rerank  │
            │ citations • diffs • authoring  │
            └───┬───────────────────────┬────┘
       lexical/suggest            semantic/hybrid
                │                       │
     ┌──────────▼─────────┐   ┌─────────▼──────────┐
     │     PostgreSQL     │   │       Qdrant       │
     │ entities • FTS     │   │ dense + sparse     │
     │ pg_trgm suggest    │   │ payload filters    │
     └──────────┬─────────┘   └─────────┬──────────┘
                │                       │
                └──────────┬────────────┘
                           │
              ┌────────────▼────────────┐         ┌───────────────────┐
              │   Ollama (host, GPU)    │◄────────│  CPU: BGE-M3 +     │
              │   qwen3:8b  (≤8K ctx)   │         │  bge-reranker-v2   │
              └────────────┬────────────┘         └───────────────────┘
                           │
              ┌────────────▼────────────┐   broker: Redis
              │   Celery workers + beat │
              │ crawl • parse • diff •  │
              │ embed • re-ingest       │
              └────────────┬────────────┘
        ┌──────────────────┼───────────────────────┐
 ┌──────▼───────┐  ┌───────▼────────┐      ┌────────▼─────────┐
 │ git collectors│  │ feed collectors│      │ web/scrape       │
 │ clone/pull    │  │ releases.atom  │      │ eudi.dev docs,   │
 │ repo content  │  │ tags/commits   │      │ conformance, EC, │
 │               │  │                │      │ issues/PR HTML   │
 └───────────────┘  └────────────────┘      └──────────────────┘
                  │ parsers: Trafilatura / Docling / heading chunking │
```

## 4. Ingestion plane
**Collectors (token-free, see CLAUDE.md GitHub policy):**
- *git collector* — clone/pull each EUDI repo; the corpus (ARF main, annexes, specs,
  roadmap markdown, changelogs) comes from files in git, not the API.
- *feed collector* — `releases.atom`, `tags.atom`, `commits/{branch}.atom` per repo for
  "what changed" without touching the REST bucket.
- *web collector* — httpx + Trafilatura over the static MkDocs sites (eudi.dev, docs.eudi.dev,
  conformance.eudi.dev) and the EC page; Playwright only when a page needs JS.
- *scrape collector* — issue/PR/discussion list pages as HTML for dashboard activity.
- *(optional) github_api collector* — enabled only if `GITHUB_TOKEN` is present.

**Parsing & normalization:**
- Docling for PDF/DOCX/PPTX (background only); Trafilatura for HTML; markdown parsed directly.
- **Heading-aware chunking** so a chunk maps to a real Section with a deep-linkable anchor.
- **Tiering** assigns authority tier (normative/reference/roadmap/community) per source rule.
- **Snapshot + diff**: store a SourceSnapshot per fetch; when a new tag/release appears,
  compute and store the diff so "what changed between versions" is answerable.

**Indexes (dual):**
- *latest-only index* — operational search ("what is true now").
- *history index* — version-to-version diff queries.

**Entities** (Postgres): Document, Section, Version/Tag, Release, Issue, Discussion,
PullRequest, Milestone, RoadmapItem, SourceSnapshot, GeneratedDraft. Vectors + payload in Qdrant.

## 5. Query plane
For every query:
1. **Lexical** — Postgres FTS for exact identifiers, section names, standards numbers, tags.
2. **Fuzzy/typeahead** — `pg_trgm` for typo-tolerant autosuggest from titles/headings/labels/logs.
3. **Semantic/hybrid** — Qdrant dense + sparse (BGE-M3) with payload filters (tier/version/repo/section).
4. **Fuse** — Reciprocal Rank Fusion across lexical + dense + sparse result lists.
5. **Rerank** — bge-reranker-v2-m3 over the top ~30 fused candidates (CPU).
6. **Ground & generate** — qwen3:8b produces an answer with a **citation block per claim cluster**:
   `{doc_title, source_url, tier, version_or_tag, section_heading, last_seen}`. Deep-link to
   section anchors for docs; surface issue/PR/release/discussion URLs directly for GitHub-derived facts.

## 6. Dashboard (four specific live views — not generic analytics)
- **Latest Releases & What Changed** — from release feeds + computed version diffs.
- **Roadmap & Planned Work** — from the reference-implementation roadmap + feature map + STS roadmap.
- **Open Issues & Feature Requests** — from scraped issue/PR list pages.
- **Current Activity** — synthesized from recently-updated PRs/issues/discussions/conformance drafts.
Every card is clickable back to its primary source (release, issue, roadmap item, doc section).

## 7. Authoring plane
Evidence-backed drafting, not autonomous authorship. User selects an evidence set; the app
generates an FAQ / troubleshooting playbook / KB article where **every section inherits the
citations and version stamps** of its source chunks. The draft is produced with a "source
basis" attached and must be explicitly finalized/published by a human — important because
some sources are live roadmaps or explicitly non-normative.

## 8. Scheduling & freshness
Celery Beat polls: GitHub feeds + scrape several times/day; crawl eudi.dev / docs.eudi.dev /
conformance.eudi.dev / EC page at least daily; detect new ARF tags & reference-implementation
releases and trigger targeted re-ingestion + diff. Keep both the latest-only and history indexes current.

## 9. Deployment
Single-user Docker Compose: `postgres`, `qdrant`, `redis`, `api` (FastAPI), `worker` + `beat`
(Celery), `web` (Next.js). **Ollama runs on the host** for reliable GPU access; containers reach
it via `host.docker.internal`. (An optional GPU-in-compose Ollama service is included but
commented — host is the default because consumer-laptop GPU passthrough is fiddly.)

## 10. Explicitly deferred (v2)
Fine-tuning (PEFT/TRL, LoRA/QLoRA), multi-user auth/RBAC, and review/publication workflows.
Leave seams, build nothing dependent on them. The right v1 is a source-aware, version-aware,
hybrid-retrieval, citation-first workbench with daily mirroring and local authoring.
