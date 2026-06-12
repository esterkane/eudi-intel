---
name: local-inference
description: How local model serving works on the 8GB RTX 4060 — Ollama setup and model pulls, the VRAM budget and context cap, wiring the CPU embedding and reranker, and health checks. Load this when building the generation service, the embedding/rerank services, or the /health endpoint.
---

# Local Inference (RTX 4060, 8 GB VRAM)

The 8 GB ceiling is the whole reason this is structured the way it is. Obey CLAUDE.md's
VRAM rules. The GPU runs the LLM only; embeddings and reranking are CPU.

## Generation — Ollama on the host
- Ollama serves an OpenAI-compatible API at `http://host.docker.internal:11434` (from
  containers) / `http://localhost:11434` (from host). The app reads `OLLAMA_BASE_URL`.
- Model: `GEN_MODEL=qwen3:8b` (Q4_K_M GGUF). Pull once: `ollama pull qwen3:8b`.
  Multilingual (good for member-state content), strong small reasoner, ~5–6 GB at 8K ctx.
- **Cap context at `GEN_CONTEXT_TOKENS=8192`.** Pass `num_ctx`/options accordingly. Going higher
  pushes layers to system RAM → 4–5× slowdown. Keep retrieved context within this budget (this is
  why reranking trims to a short, high-value set before generation).
- Optional upgrade only if you've verified headroom: `qwen3.5:9b` text-only tag, still ≤8K ctx.
  Do not change the default silently.
- Call pattern: OpenAI-compatible `/v1/chat/completions` against Ollama, or the native
  `/api/chat`. Stream tokens to the UI. Low temperature for grounded answers.

## Embeddings — BGE-M3 on CPU
- `EMBEDDING_MODEL=BAAI/bge-m3`. Run via **FastEmbed** (ONNX, CPU-efficient) or
  sentence-transformers on CPU. Produces **dense + sparse** vectors (use both in Qdrant hybrid).
- Heavy embedding = ingestion batches in Celery workers (background). At query time you embed only
  the single query string — cheap on CPU.
- Never load BGE-M3 on the GPU; the GPU is for the LLM.

## Reranker — bge-reranker-v2-m3 on CPU
- `RERANKER_MODEL=BAAI/bge-reranker-v2-m3`. Cross-encoder; score (query, candidate) pairs.
- Apply ONLY to the top `RERANK_CANDIDATES` (default 30) fused candidates. ~1–3 s on CPU is fine.
- Make it toggleable (`RERANK_ENABLED`) so you can drop it if latency bites on this laptop.

## Memory budget you must keep
- GPU: LLM ≈ 6 GB. Verify with `nvidia-smi` during a query — it must NOT climb because
  embeddings/reranking are running on the GPU. If it does, you wired a model to CUDA by mistake.
- RAM: Postgres + Qdrant + Redis + API + workers + (BGE-M3 ~2 GB) + (reranker ~2 GB) ≈ 8–12 GB,
  Next.js dev ~0.5 GB, Playwright Chromium when crawling ~0.5–1 GB. Fine within 32 GB.

## /health endpoint (Phase 0 gate)
Return component status for: Postgres (SELECT 1), Qdrant (collections reachable), Redis (PING),
Ollama (`GET /api/tags` lists `GEN_MODEL`), and a tiny generation smoke ("reply OK"). All green = gate met.

## Failure modes to guard
- Ollama not running on host → API must surface a clear "LLM unavailable" rather than hang.
- Model not pulled → `/health` reports missing model with the exact `ollama pull` command.
- Context overflow → truncate retrieved evidence to the budget before calling the model; log when trimming.
