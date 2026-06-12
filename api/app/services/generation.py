"""Phase 5: grounded generation (local-inference + hybrid-search skills).

qwen3:8b (host Ollama, GPU, ≤8K ctx) answers strictly from retrieved evidence.
Hard rules implemented here, not just prompted:
- citations[] is built ONLY from markers that resolve to real retrieved
  evidence — a fabricated [n] can never become a citation;
- insufficient evidence yields the explicit refusal phrase, never an invented
  source;
- the evidence block is trimmed to the 8K context budget BEFORE the call.

Plain async functions, no FastAPI coupling.
"""

from __future__ import annotations

import logging
import re

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.services.retrieval import Citation, SearchFilters, SearchHit, hybrid_search

logger = logging.getLogger(__name__)

REFUSAL_PHRASE = "not supported by sources"

_MARKER = re.compile(r"\[(\d+)\]")
_GEN_TIMEOUT_SECONDS = 300.0
# Token budget at ~4 chars/token: reserve room for the system prompt, the
# question, chat overhead, and the answer itself; the rest carries evidence.
_PROMPT_OVERHEAD_TOKENS = 700
_ANSWER_RESERVE_TOKENS = 1024

_SYSTEM_PROMPT = f"""\
You are a grounded assistant for the EU Digital Identity (EUDI) ecosystem.
Answer ONLY from the numbered evidence blocks provided. Hard rules:
1. Every factual claim must end with the marker(s) of its supporting evidence,
   like [1] or [2][3]. Never state a fact without a marker.
2. Use ONLY the provided evidence. Do not use prior knowledge.
3. If the evidence does not contain the information needed to answer, reply
   with exactly: "{REFUSAL_PHRASE}" and nothing else.
4. Note the authority tier of each block: normative > reference > roadmap >
   community. When several blocks support the same claim, cite the
   highest-tier block. Never present community/discussion content as binding
   requirements.
5. Be concise and factual."""


class EvidenceBlock(BaseModel):
    index: int  # 1-based marker number
    citation: Citation
    content: str


class GroundedAnswer(BaseModel):
    query: str
    answer: str
    insufficient_evidence: bool
    citations: list[Citation]  # only evidence actually cited by the answer
    cited_indices: list[int]
    invalid_markers: list[int]  # markers that resolved to nothing (dropped)
    evidence: list[EvidenceBlock]  # full retrieved set, for UI display
    evidence_trimmed: bool


class LlmUnavailableError(RuntimeError):
    """Raised when Ollama cannot be reached — surfaced as 503, never a hang."""


_AUTHORITY_TIERS = ("normative", "reference")
_AUTHORITY_RESERVED_SLOTS = 3


def select_evidence(pool: list[SearchHit], max_evidence: int) -> list[SearchHit]:
    """Evidence-layer enforcement of the CLAUDE.md tier rule: when normative or
    reference hits exist anywhere in the retrieval pool, they get reserved
    slots so discussion prose cannot crowd them out of the evidence set.
    Original ranking order is preserved among the selected hits."""
    if len(pool) <= max_evidence:
        return list(pool)
    reserved = min(_AUTHORITY_RESERVED_SLOTS, max_evidence)
    chosen = {
        i
        for i, hit in list(enumerate(pool))
        if hit.citation.tier in _AUTHORITY_TIERS
    }
    chosen = set(sorted(chosen)[:reserved])
    for i in range(len(pool)):
        if len(chosen) >= max_evidence:
            break
        chosen.add(i)
    return [pool[i] for i in sorted(chosen)]


def build_evidence_blocks(hits: list[SearchHit]) -> list[EvidenceBlock]:
    return [
        EvidenceBlock(index=i + 1, citation=hit.citation, content=hit.content)
        for i, hit in enumerate(hits)
    ]


def trim_to_budget(blocks: list[EvidenceBlock], settings: Settings) -> tuple[list[EvidenceBlock], bool]:
    """Keep whole blocks (in rank order) within the evidence token budget."""
    budget = settings.gen_context_tokens - _PROMPT_OVERHEAD_TOKENS - _ANSWER_RESERVE_TOKENS
    kept: list[EvidenceBlock] = []
    used = 0
    for block in blocks:
        cost = len(block.content) // 4 + 60  # content + metadata header
        if used + cost > budget:
            break
        kept.append(block)
        used += cost
    trimmed = len(kept) < len(blocks)
    if trimmed:
        logger.info("evidence trimmed to context budget: kept %d of %d blocks", len(kept), len(blocks))
    return kept, trimmed


def render_prompt(query: str, blocks: list[EvidenceBlock]) -> str:
    parts: list[str] = []
    for block in blocks:
        c = block.citation
        parts.append(
            f"[{block.index}] (tier: {c.tier} | doc: {c.doc_title} | "
            f"section: {c.section_heading} | version: {c.version_or_tag or 'n/a'})\n"
            f"{block.content}"
        )
    evidence_text = "\n\n".join(parts)
    return f"EVIDENCE:\n{evidence_text}\n\nQUESTION: {query}"


def parse_citations(
    answer: str, blocks: list[EvidenceBlock]
) -> tuple[list[Citation], list[int], list[int]]:
    """Markers → (citations, valid indices, invalid markers). Citations can
    only come from real evidence, by construction."""
    by_index = {block.index: block for block in blocks}
    cited: list[int] = []
    invalid: list[int] = []
    for raw in _MARKER.findall(answer):
        index = int(raw)
        if index in by_index:
            if index not in cited:
                cited.append(index)
        elif index not in invalid:
            invalid.append(index)
    citations = [by_index[i].citation for i in cited]
    return citations, cited, invalid


def is_refusal(answer: str) -> bool:
    return REFUSAL_PHRASE in answer.lower()


async def _call_ollama(prompt: str, settings: Settings) -> str:
    payload = {
        "model": settings.gen_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": False,
        "options": {
            "num_ctx": settings.gen_context_tokens,
            "temperature": 0.1,
            "num_predict": _ANSWER_RESERVE_TOKENS,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_GEN_TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise LlmUnavailableError(f"Ollama unavailable at {settings.ollama_base_url}: {exc}") from exc
    content = str(resp.json().get("message", {}).get("content", "")).strip()
    return content


_POOL_SIZE = 30  # full reranked pool; evidence is selected tier-aware from it


async def answer_query(
    query: str, filters: SearchFilters, settings: Settings, max_evidence: int = 8
) -> GroundedAnswer:
    pool = await hybrid_search(query, filters, _POOL_SIZE, settings)
    hits = select_evidence(pool, max_evidence)
    blocks = build_evidence_blocks(hits)
    blocks, trimmed = trim_to_budget(blocks, settings)

    if not blocks:
        return GroundedAnswer(
            query=query,
            answer=REFUSAL_PHRASE.capitalize(),
            insufficient_evidence=True,
            citations=[],
            cited_indices=[],
            invalid_markers=[],
            evidence=[],
            evidence_trimmed=trimmed,
        )

    answer = await _call_ollama(render_prompt(query, blocks), settings)
    refusal = is_refusal(answer)
    citations, cited, invalid = ([], [], []) if refusal else parse_citations(answer, blocks)
    if not refusal and not citations:
        # An answer with no valid citation is an uncited claim (CLAUDE.md
        # guardrail) — treat it as unsupported rather than asserting it.
        logger.warning("uncited answer collapsed to refusal for query: %s", query)
        refusal = True
    if refusal:
        answer = REFUSAL_PHRASE.capitalize()
        citations, cited, invalid = [], [], []

    return GroundedAnswer(
        query=query,
        answer=answer,
        insufficient_evidence=refusal,
        citations=citations,
        cited_indices=cited,
        invalid_markers=invalid,
        evidence=blocks,
        evidence_trimmed=trimmed,
    )
