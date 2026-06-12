"""HTML → markdown via Trafilatura, then heading-aware chunking.

Used for crawl sources (MkDocs sites, EC page). Heading slugs produced by the
markdown chunker match MkDocs' own heading ids (both GitHub-style), so anchors
deep-link into the rendered page.
"""

from __future__ import annotations

import trafilatura

from app.parsers.markdown import SectionChunk, chunk_markdown


def html_to_markdown(html: str) -> str | None:
    """Extract main content as markdown (headings preserved). None if empty."""
    return trafilatura.extract(
        html,
        output_format="markdown",
        include_links=True,
        include_tables=True,
        favor_recall=True,
    )


def chunk_html(html: str, page_url: str) -> list[SectionChunk]:
    markdown = html_to_markdown(html)
    if not markdown:
        return []
    return chunk_markdown(markdown, page_url)
