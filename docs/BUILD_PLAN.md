# BUILD_PLAN.md — ordered phases with test gates

Build the **full system**, but in safe layers. Do not advance past a phase until its
**gate** is green. Each gate is a concrete, checkable condition. The `run-and-test` skill
has the commands; this file is the sequence and the acceptance criteria.

---

### Phase 0 — Scaffold & infra
- Create the repo layout (see CLAUDE.md). FastAPI app with `/health`. Next.js app shell.
- `docker-compose.yml` brings up postgres + qdrant + redis. Alembic baseline migration.
- Ollama on host; `ollama pull qwen3:8b`. API `OLLAMA_BASE_URL` reachable.
- **Gate:** `docker compose up -d` healthy; `GET /health` returns DB+Qdrant+Redis+Ollama all OK;
  a one-line prompt to the model returns text.

### Phase 1 — Source registry & collectors
- Implement the source registry (from `eudi-source-registry` skill) as config/data.
- Collectors: `git` (clone/pull), `feed` (releases/tags/commits atom), `web` (httpx+Trafilatura),
  `scrape` (issue/PR/discussion HTML). Optional `github_api` behind `GITHUB_TOKEN`.
- Persist raw `SourceSnapshot` rows (url, fetched_at, content_hash, raw payload ref).
- **Gate:** running each collector once lands snapshots for every registered source in Postgres;
  re-running does not duplicate (dedupe by url + content_hash).

### Phase 2 — Parse, chunk, tier, snapshot/diff
- Parsers: markdown direct, Trafilatura HTML, Docling PDF (background). Heading-aware chunking.
- Populate entities: Document, Section, Version/Tag, Release, Issue, Discussion, PullRequest,
  Milestone, RoadmapItem.
- Assign authority tier per source rule. Compute version diffs when a new tag appears.
- **Gate:** Documents/Sections/Versions populated with correct tiers; a known ARF version bump
  produces a stored diff; each Section has a deep-linkable anchor/URL.

### Phase 3 — Embedding & vector indexing
- BGE-M3 (CPU) embeds chunks in Celery workers. Write dense + sparse vectors + payload
  (tier, version, repo, section, last_seen) to Qdrant. Maintain latest-index + history-index.
- **Gate:** Qdrant collections populated; a filtered vector query (e.g., tier=normative,
  version=latest) returns the expected chunks.

### Phase 4 — Hybrid search + rerank + citations
- Query plane: Postgres FTS + pg_trgm + Qdrant dense/sparse → RRF fusion → bge-reranker (CPU,
  top ~30) → citation block assembly. Autosuggest endpoint from pg_trgm.
- **Gate:** a query for an exact spec/section returns it ranked first; results carry full
  citation objects with tier + version + last_seen; autosuggest returns title matches under typos.

### Phase 5 — Grounded generation
- `qwen3:8b` generates answers constrained to retrieved evidence, with a citation block per
  claim cluster. Refuse/flag when evidence is insufficient — no fabrication.
- **Gate:** answers cite only real retrieved sources; an unanswerable query yields an explicit
  "not supported by sources" rather than an invented citation.

### Phase 6 — Dashboard (4 live views)
- Releases/What-Changed, Roadmap/Planned, Open Issues, Current Activity. Server components.
- Use the `frontend-design` public skill for the UI styling pass.
- **Gate:** all four views render from live data; every card click-throughs to its primary
  source URL (release/issue/roadmap/section).

### Phase 7 — Authoring
- Generate FAQ / playbook / KB from a selected evidence set; sections inherit citations +
  version stamps; draft carries "source basis"; human finalize/publish step.
- **Gate:** a generated draft shows per-section provenance and cannot be published without an
  explicit finalize action.

### Phase 8 — Scheduling & freshness
- Celery Beat: feeds/scrape several times daily; full crawl ≥ daily; new tag/release → targeted
  re-ingest + diff. Update both indexes.
- **Gate:** simulating a new release tag triggers re-ingestion of that version and a fresh diff,
  and the dashboard "What Changed" view reflects it.

---

## Cross-cutting acceptance
- **No GPU spill:** with the LLM loaded, `nvidia-smi` stays within budget during a query (LLM on
  GPU, embed/rerank on CPU). If not, reduce context or candidate count — never load retrieval
  models on the GPU.
- **Token-free works:** the whole pipeline runs with `GITHUB_TOKEN` empty. Setting it only makes
  GitHub collection faster, nothing breaks when it's absent.
- **Provenance everywhere:** no search result, answer, dashboard card, or authored section exists
  without a citation/source link, tier, and last_seen.
