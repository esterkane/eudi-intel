"""Read-only MCP layer for the EUDI workbench.

Thin FastMCP adapters over the existing retrieval / registry core. The query
plane is exposed to agents as three read-only tools — `hybrid_search`,
`get_chunk`, `list_sources` — with structured errors and full provenance
preserved on every result. The authoring / publish plane is human-gated and is
deliberately NOT exposed here; nothing in this package mutates state.
"""
