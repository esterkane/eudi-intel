---
name: run-and-test
description: How to bring up the stack, smoke-test it, run integration tests, and run the grounding/eval harness — plus the per-phase gate checks. Load this whenever you need to run, verify, or test the app, or before advancing a build phase.
---

# Run & Test

## Bring-up
```bash
# 1. Host Ollama (GPU)
ollama serve &              # if not already running
ollama pull qwen3:8b

# 2. Config
cp .env.example .env

# 3. Infra
docker compose up -d postgres qdrant redis
# wait for healthchecks: docker compose ps

# 4. Migrations + app
docker compose run --rm api alembic upgrade head
docker compose up -d api worker beat web
```
Use the MCP tools while developing: **postgres** (inspect schema/rows), **qdrant** (inspect
collections/payloads), **playwright** (crawl tests + drive the Next.js UI), **fetch** (page checks).

## Phase 0 — health gate
```bash
curl -s localhost:8000/health | jq
```
Expect all green: postgres, qdrant, redis, ollama (model present), generation smoke.

## Phase 1 — collectors gate
- Trigger each collector once (`POST /ingest/run-all` or per-source endpoints).
- Verify via postgres MCP: `SELECT source_id, count(*) FROM source_snapshots GROUP BY 1;`
- Re-run and confirm no duplicate Documents (dedupe by url + content_hash).

## Phase 2 — parse/tier/diff gate
- `SELECT tier, count(*) FROM documents GROUP BY 1;` — tiers assigned, normative present.
- Confirm Sections have anchor URLs. Confirm a known ARF tag bump produced a stored diff.

## Phase 3 — embedding/index gate
- qdrant MCP: collections `eudi_latest` + `eudi_history` populated.
- Filtered vector query (tier=normative, version=latest) returns expected chunks.

## Phase 4 — hybrid search gate
- Query an exact spec/section name → it ranks first (lexical path works).
- Every result carries full citations (tier + version + last_seen).
- `GET /suggest?q=<typo>` returns the right title (pg_trgm works).

## Phase 5 — grounding gate (eval harness)
Build a small eval set (`tests/eval/grounding.jsonl`) of EUDI questions with known-supporting
sources. For each:
- Assert every claim in the answer maps to a real retrieved citation.
- Assert an unanswerable/out-of-scope question returns an explicit "not supported by sources"
  rather than a fabricated citation.
Track: citation-precision (cited sources actually contain the claim) and refusal-correctness.

## Phase 6 — dashboard gate
- Playwright MCP: load `localhost:3000`, assert all four views render and each card has a
  click-through href to a primary source URL.

## Phase 7 — authoring gate
- `POST /author/draft` with an evidence set → draft has per-section citations + source_basis.
- Confirm publish requires an explicit finalize call (no auto-publish).

## Phase 8 — scheduling gate
- Inject/simulate a new release tag in a feed fixture → confirm targeted re-ingest + new diff,
  and the "What Changed" view updates.

## Cross-cutting checks (run before declaring done)
- **No GPU spill:** run a query and watch `nvidia-smi` — VRAM stays in budget (LLM only on GPU).
- **Token-free:** full pipeline runs with `GITHUB_TOKEN` empty; setting it only speeds GitHub collection.
- **Provenance everywhere:** no search result / answer / card / authored section lacks a citation,
  tier, and last_seen.

## Test tooling
- Python: `pytest` (unit + integration), httpx test client for API, fixtures for collectors
  (record sample feeds/HTML so tests don't hit the network).
- Web: Playwright e2e for the four dashboard views + the search + authoring flows.
- Keep collector tests offline using recorded fixtures; only the live-ingest smoke hits the network.
