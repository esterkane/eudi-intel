# EUDI Intelligence & Authoring Workbench

A local, fully open-source intelligence workbench for the EU Digital Identity (EUDI)
ecosystem: it mirrors EUDI's official docs, roadmap repos, releases, issues and
conformance material, then provides **grounded citation-first search**, a
**"what changed / what's active" dashboard**, and **evidence-backed authoring**
(FAQs, troubleshooting playbooks, KB articles).

Runs on a single laptop (built and tuned for an **RTX 4060 8 GB / 32 GB RAM**).
Fully open-source, Docker-based, local inference via Ollama.

## This repository is a Claude Code build package
The app is implemented **by Claude Code** from the contract in this repo. If you opened
this, the important files are:
- **`CLAUDE.md`** — the build contract and hard constraints (read first).
- **`docs/ARCHITECTURE.md`** — the full architecture.
- **`docs/BUILD_PLAN.md`** — phased build order with test gates.
- **`.claude/skills/`** — operational skills Claude Code loads per task.
- **`.mcp.json`** — MCP tools (postgres, qdrant, playwright, fetch) for development.

To build: open this folder in Claude Code and say *"Read CLAUDE.md and start at Phase 0
of docs/BUILD_PLAN.md."* It will scaffold, implement, run, and test each phase against its gate.

## Quickstart (once built)
1. Install [Ollama](https://ollama.com) on the host and pull the model:
   ```bash
   ollama serve &
   ollama pull qwen3:8b
   ```
2. Configure env:
   ```bash
   cp .env.example .env
   ```
3. Bring up infra and the app:
   ```bash
   docker compose up -d postgres qdrant redis
   docker compose up -d api worker beat web
   ```
4. Open the dashboard at `http://localhost:3000`. Trigger an initial ingest from the UI
   or `POST http://localhost:8000/ingest/run-all`.

## Notes
- **No GitHub token required.** Ingestion uses `git clone` + Atom feeds + HTML scraping.
  Add a `GITHUB_TOKEN` to `.env` later only if you want faster GitHub collection.
- **8 GB VRAM rules are enforced in CLAUDE.md.** The LLM is the only thing on the GPU;
  embeddings and reranking run on CPU. Keep the model context at 8K.
- Fine-tuning, multi-user auth, and review workflows are deferred to v2.

## Stack
Next.js · FastAPI · PostgreSQL (FTS + pg_trgm) · Qdrant · Celery + Redis · Ollama
(`qwen3:8b`) · BGE-M3 + bge-reranker-v2-m3 · Playwright / Trafilatura / Docling.
