# CLAUDE.md — EUDI Intelligence & Authoring Workbench

> Read this file first, every session. It is the build contract. The skills in
> `.claude/skills/` hold the operational detail; this file says what we are
> building, the constraints you must never violate, and the order to build in.

## Mission
A **local, fully open-source intelligence workbench** for the EU Digital Identity
(EUDI) ecosystem. It mirrors EUDI's official docs, roadmap repos, releases, issues,
and conformance material into a local store, then provides **grounded, citation-first
search**, a **"what changed / what's active" dashboard**, and **evidence-backed
authoring** (FAQs, troubleshooting playbooks, KB articles). It is *not* a generic
chat-over-docs app. Every answer and every generated draft carries source provenance,
version/tag, and a last-seen date.

## Hardware envelope — NON-NEGOTIABLE
Target machine: **laptop, NVIDIA RTX 4060 (8 GB VRAM), 32 GB system RAM, single user.**
The 8 GB VRAM ceiling drives the whole inference design. Treat these as hard rules:

1. **The GPU is reserved for the LLM only.** The generation model runs on the GPU via
   Ollama. The embedding model and the reranker run on **CPU**. Never load all three on
   the GPU at once — it will spill to system RAM and slow everything 4–5×.
2. **Cap the LLM context window at 8K tokens** (8192) for interactive use. Larger
   contexts push the model out of VRAM on this card.
3. **Default models** (verify latest tags at build time, but do not exceed these sizes):
   - Generation: `qwen3:8b` (Q4_K_M GGUF via Ollama). ~5–6 GB VRAM at 8K ctx. Multilingual.
   - Embeddings: `BAAI/bge-m3` on CPU via FastEmbed/ONNX (dense + sparse). ~2 GB RAM.
   - Reranker: `BAAI/bge-reranker-v2-m3` on CPU, applied to top ~30 candidates only. ~2 GB RAM.
4. **Embedding is a background job.** Heavy embedding happens in Celery workers during
   ingestion. At query time you embed only the single query string + rerank a short list.
5. If you ever benchmark and the box has headroom, an upgrade path is `qwen3.5:9b` (text-only
   tag) — but only if context stays ≤8K. Do not silently change the default model.

A rough memory map you must respect (see `local-inference` skill for detail):
GPU: LLM ~6 GB. RAM: Postgres+Qdrant+Redis+API+workers+embed/rerank models ≈ 8–12 GB,
Next.js dev ≈ 0.5 GB, Playwright Chromium when crawling ≈ 0.5–1 GB. Comfortable in 32 GB.

## Final tech stack (decisions are made — do not re-litigate)
- **Frontend:** Next.js (App Router, TypeScript) — dashboard, search UX, authoring UI.
- **Backend:** FastAPI (Python 3.11+) — ingestion APIs, query orchestration, citations, drafts.
- **Relational + lexical:** PostgreSQL 16 with full-text search + `pg_trgm` (autosuggest, exact-title).
- **Vector:** Qdrant — dense + sparse hybrid queries with payload filters (tier/version/repo/section).
- **Jobs/schedule:** Celery + Celery Beat with **Redis** as broker (not RabbitMQ — lighter on a laptop).
- **Crawl/extract:** `git` (clone/pull) for repo content, `httpx` + Trafilatura for static MkDocs
  pages, Playwright only as a JS-render fallback, Docling background-only for PDFs.
- **LLM serving:** **Ollama** on the host (OpenAI-compatible API at `:11434`). The app talks to
  it over `OLLAMA_BASE_URL`. Ollama wraps llama.cpp and handles GGUF + GPU offload.
- **Retrieval models:** BGE-M3 (embed) + bge-reranker-v2-m3 (rerank), both CPU.
- **Fine-tuning:** OUT OF SCOPE for v1. Retrieval-first. Leave clean seams (a `training/` dir
  stub) for later PEFT/TRL + LoRA/QLoRA, but build nothing that depends on it.

## Architecture (summary — full version in `docs/ARCHITECTURE.md`)
Two planes:
- **Ingestion plane:** collectors (git/feeds/crawl/scrape) → parsers (Trafilatura/Docling,
  heading-aware chunking) → source-authority tiering → snapshot + diff → embed → Postgres + Qdrant.
- **Query plane:** hybrid retrieval (Postgres FTS + pg_trgm + Qdrant dense/sparse) → RRF fusion →
  CPU rerank → grounded generation with a citation block per claim cluster.

First-class entities (model these explicitly, not raw blobs): Document, Section, Version/Tag,
Release, Issue, Discussion, PullRequest, Milestone, RoadmapItem, SourceSnapshot, GeneratedDraft.

## Source authority tiers — apply BEFORE ranking/generation
1. **Normative** — latest ARF Annex 2 + formal technical specifications. Outranks everything.
2. **Reference/technical** — ARF main narrative, other annexes, technical specs.
3. **Implementation/roadmap** — reference-implementation roadmap, feature map, STS roadmap, releases.
4. **Community/feedback** — discussion papers, issues, PR threads. Always label as non-normative.
Retrieval and citations must surface the tier. Never let a discussion paper outrank an Annex.
The canonical source list, URLs, repos and per-source fetch method live in the
`eudi-source-registry` skill.

## GitHub access policy — NO TOKEN (token-free by design)
We were told: **public access only, no PAT.** Unauthenticated GitHub REST is **60 req/hr/IP**,
and the ETag 304-doesn't-count optimization does **not** apply to unauthenticated requests. So:
- **Document corpus** (ARF, annexes, specs, changelogs, roadmap markdown): `git clone --depth 1`
  then `git fetch` on schedule. No REST API. No rate limit.
- **Releases / tags / commit activity**: GitHub **Atom feeds**
  (`https://github.com/{owner}/{repo}/releases.atom`, `/tags.atom`, `/commits/{branch}.atom`).
  Public, outside the REST bucket. This powers "what changed".
- **Issues / PRs / discussions activity**: HTML-scrape the list pages (httpx + Trafilatura, or
  Playwright if JS-rendered). Do NOT poll the REST API in token-free mode beyond a tiny hard
  budget (≤ ~30 calls/hr, reserved for emergencies).
- **Optional upgrade:** if `GITHUB_TOKEN` is set in `.env`, collectors switch to authenticated
  REST (5,000 req/hr) and use ETag caching. Build this as a clean strategy switch; default off.

## Target repo layout (create this)
```
eudi-intel/
├── api/                 # FastAPI app
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/     # search, dashboard, authoring, ingest, health
│   │   ├── services/    # retrieval, rerank, generation, citations, diffing
│   │   ├── collectors/  # git, feeds, crawl, scrape (+ optional github_api)
│   │   ├── parsers/     # trafilatura, docling, chunking, tiering
│   │   ├── models/      # SQLAlchemy + pydantic schemas
│   │   ├── worker/      # celery app, beat schedule, tasks
│   │   └── db/          # migrations (alembic), qdrant client
│   └── pyproject.toml
├── web/                 # Next.js app (App Router, TS)
├── training/            # v2 stub only (PEFT/TRL) — do not implement now
├── docker-compose.yml
├── .env.example  .env   # .env is gitignored
├── .mcp.json
├── CLAUDE.md
└── docs/  .claude/skills/
```

## How to run (dev) & how to test
- **Bring up infra:** `docker compose up -d postgres qdrant redis` then run API + worker + web.
- **Ollama** runs on the host: `ollama serve` + `ollama pull qwen3:8b`. App reaches it at
  `OLLAMA_BASE_URL` (`http://host.docker.internal:11434` from containers; `localhost` from host).
- **Full details, smoke tests, and the eval harness are in the `run-and-test` skill.** Use it.
- Every phase below has a test gate. Do not advance until its gate is green.

## Build order (full system, but built in safe layers — detail in `docs/BUILD_PLAN.md`)
0. Scaffold + docker-compose + health endpoints + Ollama reachable. Gate: `/health` green, model responds.
1. Source registry + collectors (git + feeds + crawl + scrape). Gate: raw snapshots land in Postgres.
2. Parsers + chunking + tiering + snapshot/diff. Gate: Documents/Sections/Versions populated, diffs computed.
3. Embedding + Qdrant indexing (latest-index + history-index). Gate: vectors searchable with filters.
4. Hybrid search + RRF + CPU rerank + citation assembly. Gate: queries return cited, tiered results.
5. Grounded generation (answers with per-cluster citations). Gate: answers cite real sources, no fabrication.
6. Dashboard: 4 live views (Releases/What Changed, Roadmap, Open Issues, Current Activity). Gate: cards click back to source.
7. Authoring: FAQ / playbook / KB with citation inheritance + "source basis" + publish gate. Gate: draft carries stamps, requires finalize.
8. Scheduling: Celery Beat polling cadence + re-ingest on new tags. Gate: a new tag triggers targeted re-ingest.

## Coding conventions
- Python: type hints everywhere, `ruff` + `black`, `pydantic` v2 schemas, async FastAPI handlers.
- TS: strict mode, server components for SSR dashboards, client components only where needed.
- Every retrieval/generation response object includes a `citations[]` array
  (`{doc_title, source_url, tier, version_or_tag, section_heading, last_seen}`) — see `hybrid-search` skill.
- Idempotent ingestion: re-running a collector must not duplicate Documents (dedupe by source URL + content hash).
- Never hardcode model names in code — read from env (`GEN_MODEL`, `EMBEDDING_MODEL`, `RERANKER_MODEL`).

## Skills index — load the relevant SKILL.md before working on that area
- `eudi-source-registry` — canonical EUDI sources, tiers, URLs/repos, per-source fetch method, freshness policy.
- `ingestion-pipeline` — collectors → parse → chunk → tier → snapshot → diff → embed → index; idempotency.
- `local-inference` — Ollama setup, model pulls, the VRAM rules, CPU embed/rerank wiring, health checks.
- `hybrid-search` — lexical + dense/sparse + RRF + rerank + citation block assembly + autosuggest.
- `dashboard-views` — the four live views and exactly where each card's data and click-through come from.
- `grounded-authoring` — FAQ/playbook/KB generation, citation inheritance, source-basis, publish workflow.
- `run-and-test` — compose bring-up, smoke tests, integration tests, grounding/eval harness, gates.
- `entity-summarization` — structured, cached, grounded summaries of issues/PRs/discussions/releases (support track S2).
- `semantic-recall` — domain glossary/alias map + LLM query expansion for vague support queries (support track S3).
- `support-console` — the support lead's fast triage surface: answer + related activity + playbook + glossary (support track S4).

## Support-lead capability track (docs/SUPPORT_PLAN.md)
A second audience — the EUDI-Wallet Technical Support Lead supporting B2B credential providers/verifiers.
Phases S1–S4 layer deep activity ingestion, structured summaries, semantic recall, and a support console
onto the v1 workbench. Same hard rules (token-free, GPU=LLM-only, provenance everywhere).

## MCP tools available during development (see `.mcp.json`)
- **postgres** — inspect schema, run queries, verify ingestion landed.
- **qdrant** — inspect collections, check vectors/payloads/filters.
- **playwright** — test crawling of eudi.dev pages AND drive the Next.js UI for end-to-end checks.
- **fetch** (optional) — pull individual EUDI pages for inspection.
To study real GitHub repo structure during dev, just `git clone` the target repos into `reference/`
(gitignored) — do not burn the 60/hr API budget exploring.

## Guardrails — do NOT
- Do not put roadmap/issue/release state into model weights. That is retrieval's job (it changes daily).
- Do not generate uncited claims. If retrieval has no support, say so; never fabricate a source.
- Do not let community/discussion content outrank normative Annex 2 / specs.
- Do not exceed the VRAM rules above. If a change risks GPU spill, stop and flag it.
- Do not auto-publish authored drafts. A human finalizes; drafts carry "source basis" until then.

---

# Onboarding reference (added by docs pass)

> The sections above are the build contract. The sections below are the quick operational
> reference an agent needs on session start: exact commands, a 5-line architecture, the
> invariants to never break, and the definition of done. Commands are drawn from
> `api/pyproject.toml`, `web/package.json`, the `run-and-test` skill, and `api/tests/README.md`.

## Run / test commands (exact)

All Python commands run from `api/`. All web commands run from `web/`.

**Bring up the stack** (host Ollama provides the GPU):
```bash
ollama serve &                       # host, if not already running
ollama pull qwen3:8b
cp .env.example .env
docker compose up -d postgres qdrant redis
docker compose run --rm api alembic upgrade head     # migrations
docker compose up -d api worker beat web
curl -s localhost:8000/health | jq    # Phase-0 health gate: postgres/qdrant/redis/ollama green
```

**Backend — install, tests, lint, types** (from `api/`):
```bash
pip install -e ".[dev]"      # add ",embed" only where FlagEmbedding/torch are needed (Docker image has it)
pytest                       # unit tests are fully offline (embeddings/LLM patched)
ruff check .
black --check .
mypy app/                    # strict mode (configured in pyproject.toml)
```

**Integration + eval tests** (need real services on a dedicated `eudi_test` DB; they SKIP,
not fail, when it is absent — see `api/tests/README.md`):
```bash
docker compose exec -T postgres psql -U eudi -d eudi -c "CREATE DATABASE eudi_test;"
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://eudi:eudi@postgres:5432/eudi_test \
  api alembic upgrade head
pytest                       # integration tests now run against eudi_test
RUN_GROUNDING_EVAL=1 pytest tests/test_grounding_eval.py   # opt-in grounding gate
RUN_RECALL_EVAL=1   pytest tests/test_recall_eval.py       # opt-in recall gate
```

**Frontend** (from `web/`):
```bash
npm install
npm run dev      # next dev on :3000
npm run build
npm run lint     # next lint (no custom eslint config; Next defaults)
npm run e2e      # Playwright e2e: dashboard, search, drafts, support flows
```

**Quality gate / CI:** there is **no CI workflow** in this repo (no `.github/workflows/`,
no Makefile/tox/nox). The gate is the per-phase manual gate in the `run-and-test` skill plus
the commands above. Treat green `pytest` + `ruff check` + `black --check` + `mypy app/` (API)
and `npm run lint` + `npm run build` + `npm run e2e` (web) as the local quality gate.

## Architecture in 5 lines
1. **Ingestion plane** (`api/app/collectors` → `parsers` → `services/snapshots`,`parse_pipeline`,`version_diff`): git clone + Atom feeds + HTML scrape of EUDI sources, token-free by default, into Postgres with source-authority tiers and snapshot diffs.
2. **Index** (`embeddings/bge_m3.py`, `services/vector_index.py`, `db/qdrant.py`): BGE-M3 dense+sparse embeddings (CPU) written to Qdrant collections `eudi_latest` + `eudi_history`; Postgres holds FTS + `pg_trgm`.
3. **Query plane** (`services/retrieval.py`, `embeddings/reranker.py`, `services/generation.py`,`llm.py`): hybrid lexical+vector retrieval → RRF fusion → CPU rerank → grounded generation via host Ollama (`qwen3:8b`, 8K ctx), every claim cluster carrying a citation block.
4. **Async** (`worker/celery_app.py`,`tasks.py`): Celery + Beat on Redis run ingestion/embedding on a cadence; query time only embeds the one query + reranks a short list.
5. **API + UI**: FastAPI routers (`health`,`ingest`,`search`,`dashboard`,`author`,`answer`,`support`) at `:8000`; Next.js App-Router SPA at `:3000` (dashboard, search, drafts, support console).

## Invariants I must never break
1. **Determinism / pipeline integrity** — Ingestion is idempotent: re-running a collector must not duplicate Documents (dedupe by source URL + content hash). Source-authority tiers are applied BEFORE ranking/generation; never let community/discussion content outrank normative ARF Annex 2 / specs.
2. **Quality gate passes** — `pytest`, `ruff check .`, `black --check .`, `mypy app/` (strict, no bare `# type: ignore`) for the API and `npm run lint`/`npm run build`/`npm run e2e` for web must be green. (No CI runs these for you — run them locally.)
3. **Provenance on every chunk** — Every search result, answer, dashboard card, and authored section carries a citation (`doc_title, source_url, tier, version_or_tag, section_heading, last_seen`). Never emit an uncited claim; if retrieval has no support, say so — never fabricate a source. Drafts carry "source basis" and require an explicit human finalize (no auto-publish).
4. **No secrets in git** — Config and secrets load from `.env` (gitignored) via `pydantic-settings` / Docker `env_file:`; only `.env.example` is committed, with `GITHUB_TOKEN` empty. Never hardcode credentials in `docker-compose.yml` or code.
5. **Repo-specific hard rules** — 8 GB VRAM envelope: the GPU is the LLM only (embeddings + reranker on CPU); LLM context capped at 8192 tokens; never raise model size/ctx on this card. Token-free GitHub access by default; a `GITHUB_TOKEN` only speeds collection, never required. Model names read from env (`GEN_MODEL`,`EMBEDDING_MODEL`,`RERANKER_MODEL`), never hardcoded. Schema changes require an Alembic migration. The LLM is reached only via `OLLAMA_BASE_URL`. Do not bake daily-changing roadmap/issue/release state into model weights — that is retrieval's job.

## Definition of done
- `pytest` passes (unit; integration when `eudi_test` is provisioned).
- Types pass: `mypy app/` clean under strict mode.
- Lint/format pass: `ruff check .` + `black --check .` (API); `npm run lint` + `npm run build` (web).
- Quality gate: the relevant phase gate from the `run-and-test` skill is green (no repo CI to rely on).
- Provenance/grounding intact: results/answers/cards/drafts carry full citations + tier + last_seen; unanswerable questions refuse rather than fabricate.
- VRAM / token-free invariants respected (LLM-only GPU, 8K ctx, runs with empty `GITHUB_TOKEN`).
- README / `docs/` / affected `.claude/skills/` updated if behaviour changed.
- No secrets added; only `.env.example` documents variables.
