# Agent Access — MCP server

The retrieval core is exposed to MCP clients (Claude Code, Cursor, a local
agent) as a small, **read-only** [Model Context Protocol](https://modelcontextprotocol.io)
server named **`eudi-intel`**. It is a set of **thin adapters** over the existing
retrieval and source-registry functions — no business logic lives in the MCP
layer.

> **Read-only by design.** Only the query plane is exposed. The authoring /
> publish plane is human-gated and is **not** exposed as a tool, and **no tool
> mutates state**. `MCP_ALLOW_MUTATIONS` defaults to `false` and exists only to
> make that invariant explicit — there is no mutating tool to enable.

Implementation: `api/app/mcp/` — `errors.py` (structured errors), `tools.py`
(pure importable async impls), `resources.py` (settings wiring), `server.py`
(FastMCP registration).

## Tools

### `hybrid_search(query, filters?, limit?)`
Hybrid lexical (Postgres FTS) + fuzzy heading (pg_trgm) + dense/sparse (Qdrant)
retrieval, RRF-fused, CPU-reranked, tier-ordered. Wraps
`app.services.retrieval.hybrid_search`.

- `query` (str, required, 1..500 chars)
- `filters` (object, optional): `{tier?, repo?, version?}` — `tier` is one of
  `normative | reference | roadmap | community`; `repo` is a source id (see
  `list_sources`); `version` is a version/tag string.
- `limit` (int, default 10, 1..30)

Returns `{query, count, results: [{score, content, section_path, citation}]}`,
ordered best-first. Every `citation` carries the full provenance block:
`{doc_title, source_url, tier, version_or_tag, section_heading, last_seen}` — the
same shape the HTTP `/search` endpoint returns.

### `get_chunk(chunk_id)`
Fetch one indexed chunk (parsed document section) by its integer id. Wraps
`app.services.retrieval.get_section_hit`.

- `chunk_id` (int, required, >= 1)

Returns `{chunk_id, chunk: {score, content, section_path, citation}}`. `score`
is `0.0` (a direct fetch is not ranked). An unknown id is a **business** error
(see below), not an empty result.

### `list_sources()`
List the canonical EUDI source registry. Wraps `app.collectors.registry.REGISTRY`.

Returns `{count, sources: [{id, title, tier, method, url}]}`. `tier` is the
authority label; `method` is the token-free fetch method
(`git | feed | crawl | scrape`). Static in-process data — no backend round trip.

## Error contract

Tools never raise or leak a stack trace. On failure they return a structured
payload instead of a result:

```json
{
  "isError": true,
  "errorCategory": "validation | transient | permission | business",
  "isRetryable": false,
  "message": "<safe, human-readable summary>",
  "details": { }
}
```

| Category     | Meaning                                                       | Retryable |
|--------------|---------------------------------------------------------------|-----------|
| `validation` | Bad input (empty query, unknown tier/filter key, bad limit, non-positive id). | no |
| `business`   | Valid request that cannot be satisfied (unknown `chunk_id`).   | no |
| `transient`  | A backend (Postgres / Qdrant) was momentarily unreachable, or an unexpected internal error. | yes (backend); no (internal) |
| `permission` | Reserved; no tool currently uses it (all tools are public read-only). | no |

httpx / Qdrant / SQLAlchemy connectivity errors are classified as retryable
`transient`. An empty `results` list (with no `isError`) means nothing matched —
that is a normal result, not an error.

## Running the server

Run from the `api/` package root (the same root the API imports from):

```bash
cd api
python -m app.mcp.server          # MCP_TRANSPORT=stdio (default)
```

Transport and bind address come from the environment / `.env`:

| Variable               | Default       | Meaning                                  |
|------------------------|---------------|------------------------------------------|
| `MCP_TRANSPORT`        | `stdio`       | `stdio` (Claude Code / local) or `http`  |
| `MCP_HTTP_HOST`        | `127.0.0.1`   | bind host for `http` transport           |
| `MCP_HTTP_PORT`        | `8800`        | bind port for `http` transport           |
| `MCP_ALLOW_MUTATIONS`  | `false`       | hard read-only guard (no effect today)   |

The server reuses the API's settings, async SQLAlchemy session, cached Qdrant
client, and CPU embedder/reranker — so it needs the same Postgres + Qdrant the
API uses. For `http` transport: `MCP_TRANSPORT=http python -m app.mcp.server`.

## Client registration

### Claude Code / Cursor (stdio)

```json
{
  "mcpServers": {
    "eudi-intel": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "env": { "MCP_TRANSPORT": "stdio" }
    }
  }
}
```

Set the working directory to `api/` (or run via the Docker image, where the
package root is already `api/`), so `app.mcp.server` resolves and the database /
Qdrant URLs from `.env` apply.

## Example results

`hybrid_search("strong user authentication", {"tier": "normative"}, 3)`:

```json
{
  "query": "strong user authentication",
  "count": 1,
  "results": [
    {
      "score": 0.91,
      "content": "Strong user authentication requires ...",
      "section_path": "Annex 2 > Topic 20",
      "citation": {
        "doc_title": "ARF Annex 2",
        "source_url": "https://eudi.dev/annex-2#topic-20",
        "tier": "normative",
        "version_or_tag": "1.5.0",
        "section_heading": "Topic 20 - Strong User authentication",
        "last_seen": "2026-06-12T00:00:00+00:00"
      }
    }
  ]
}
```

`get_chunk(99999)` (unknown id):

```json
{
  "isError": true,
  "errorCategory": "business",
  "isRetryable": false,
  "message": "No chunk exists with id 99999.",
  "details": { "chunk_id": 99999 }
}
```

## Tests

Offline unit tests live in `api/tests/test_mcp_tools.py` — they inject fakes for
the search service and chunk fetch (no live Postgres / Qdrant) and cover success
shape (provenance present), unknown id (business), validation errors, and a
transient backend error. Run them with `pytest tests/test_mcp_tools.py`.
