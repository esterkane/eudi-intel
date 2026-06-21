"""FastMCP server for the EUDI Intelligence & Authoring Workbench.

Exposes the retrieval core as three READ-ONLY MCP tools that any MCP client
(Claude Code, Cursor, a local agent) can call:

- ``hybrid_search``  — hybrid lexical + dense/sparse retrieval over the corpus.
- ``get_chunk``      — fetch one indexed chunk by id, with its full citation.
- ``list_sources``   — the canonical EUDI source registry (tier + fetch method).

The tool *logic* lives in :mod:`app.mcp.tools` as plain async functions; the
wrappers here supply the application Settings and the real retrieval/registry
dependencies (the impls default to them, so the wrappers stay one-liners).

READ-ONLY by design: the authoring / publish plane is human-gated and is NOT
exposed; no tool mutates state. ``MCP_ALLOW_MUTATIONS`` (default false) exists
only to make that invariant explicit — there is no mutating tool to enable.

Transport is selected by ``MCP_TRANSPORT``: ``stdio`` (default, for Claude Code
and local dev) or ``http`` (streamable-HTTP on ``MCP_HTTP_HOST`` / ``MCP_HTTP_PORT``).

Run it from the ``api/`` package root::

    python -m app.mcp.server
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.core.config import get_settings
from app.mcp.tools import get_chunk_impl, hybrid_search_impl, list_sources_impl

_settings = get_settings()
mcp = FastMCP(
    "eudi-intel",
    host=_settings.mcp_http_host,
    port=_settings.mcp_http_port,
)


@mcp.tool()
async def hybrid_search(
    query: str,
    filters: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search the EUDI corpus and return the most relevant chunks, each with full
    provenance (citation, tier, version, last-seen date).

    WHAT IT DOES: Runs the workbench's hybrid retrieval pipeline — Postgres
    full-text + pg_trgm heading match + Qdrant dense/sparse vectors, fused with
    Reciprocal Rank Fusion, CPU-reranked, then ordered so normative ARF/spec
    content is never out-ranked by community discussion at comparable relevance.

    WHEN TO USE: To gather grounded evidence about the EU Digital Identity (EUDI)
    ecosystem — the Architecture & Reference Framework (ARF), its annexes,
    technical specifications, reference-implementation roadmap, releases, and
    issues/PRs/discussions — before reasoning or composing an answer yourself.

    WHEN NOT TO USE: To fetch one already-known chunk by id (use `get_chunk`), or
    to discover which sources feed the corpus and their authority tiers (use
    `list_sources`). This tool does not generate a free-text answer.

    INPUTS:
      - query (str, required, 1..500 chars): natural-language search query.
      - filters (object, optional): narrow the search. Allowed keys:
          * tier    — "normative" | "reference" | "roadmap" | "community"
          * repo    — source id (e.g. "arf_repo"); see `list_sources`
          * version — a version/tag string (e.g. "1.5.0")
      - limit (int, default 10, 1..30): maximum results to return.

    OUTPUT: {query, count, results: [{score, content, section_path, citation:
    {doc_title, source_url, tier, version_or_tag, section_heading, last_seen}}]}.
    `results` is ordered best-first and may be empty when nothing matches. Every
    result carries the full citation block — never strip provenance.

    EDGE CASES & FAILURES: An empty `results` list with no error means nothing
    matched. On failure a structured error is returned instead:
    errorCategory="validation" (empty query, bad tier, limit out of range, not
    retryable); "transient" (Postgres or Qdrant unreachable, retryable). Stack
    traces are never returned.
    """
    return await hybrid_search_impl(query, filters=filters, limit=limit, settings=get_settings())


@mcp.tool()
async def get_chunk(chunk_id: int) -> dict[str, Any]:
    """Fetch a single indexed chunk by its id, with its full citation block.

    WHAT IT DOES: Looks up one chunk (a parsed document section) by its integer
    id and returns its text plus the same citation block search results carry —
    doc_title, source_url, tier, version_or_tag, section_heading, last_seen.

    WHEN TO USE: To re-read the full text and provenance of a chunk you already
    identified (e.g. to quote it precisely, or to inspect a neighbouring section).

    WHEN NOT TO USE: To find chunks by topic (use `hybrid_search`). The id is the
    chunk's database id, not a URL.

    INPUTS:
      - chunk_id (int, required, >= 1): the chunk's integer id.

    OUTPUT: {chunk_id, chunk: {score, content, section_path, citation: {...}}}.
    `score` is 0.0 because a direct fetch is not ranked.

    EDGE CASES & FAILURES: A structured error is returned on failure:
    errorCategory="validation" (chunk_id not a positive integer, not retryable);
    "business" (no chunk with that id exists — valid request, nothing to return,
    not retryable); "transient" (Postgres unreachable, retryable). Stack traces
    are never returned.
    """
    return await get_chunk_impl(chunk_id)


@mcp.tool()
async def list_sources() -> dict[str, Any]:
    """List the canonical EUDI sources with their authority tier and fetch method.

    WHAT IT DOES: Returns the workbench's source registry — every source that
    feeds the corpus, with its id, human title, authority tier
    ("normative" | "reference" | "roadmap" | "community"), fetch method
    ("git" | "feed" | "crawl" | "scrape"), and canonical URL.

    WHEN TO USE: During planning, to discover what the corpus is built from, to
    learn a source's authority tier before weighting its content, or to find the
    `repo` id to pass as a `hybrid_search` filter.

    WHEN NOT TO USE: To search content (use `hybrid_search`). This returns
    registry metadata only, no chunk text.

    INPUTS: none.

    OUTPUT: {count, sources: [{id, title, tier, method, url}]}.

    EDGE CASES & FAILURES: The registry is static in-process data, so this
    effectively never fails; any unexpected error is still returned as a
    structured trace-free error rather than raised.
    """
    return await list_sources_impl()


def main() -> None:
    """Run the FastMCP server on the configured transport."""
    settings = get_settings()
    if settings.mcp_transport == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
