"""Section-level diff between two tags of a docs repo (ingestion-pipeline §6).

Fetches each tag shallowly into the existing mirror (still no REST API), parses
the markdown tree at both tags, and compares section content hashes per file.
The result powers the "What Changed" dashboard and version-comparison queries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.git import run_git
from app.models.entities import VersionDiff
from app.parsers.markdown import chunk_markdown


async def _fetch_tag(mirror: Path, tag: str) -> None:
    await run_git(
        "fetch", "--depth", "1", "origin", f"refs/tags/{tag}:refs/tags/{tag}", cwd=mirror
    )


async def _markdown_files_at(mirror: Path, tag: str) -> list[str]:
    out = await run_git("ls-tree", "-r", "--name-only", tag, cwd=mirror)
    return [p for p in out.splitlines() if p.endswith(".md")]


async def _file_at(mirror: Path, tag: str, path: str) -> str:
    return await run_git("show", f"{tag}:{path}", cwd=mirror)


async def _section_hashes_at(mirror: Path, tag: str) -> dict[str, dict[str, str]]:
    """{file: {section_path: combined content hash}} for all .md files at a tag."""
    result: dict[str, dict[str, str]] = {}
    for path in await _markdown_files_at(mirror, tag):
        text = await _file_at(mirror, tag, path)
        per_path: dict[str, str] = {}
        for chunk in chunk_markdown(text, base_url=path):
            # oversize sections yield several chunks per path — combine hashes
            per_path[chunk.section_path] = (
                per_path.get(chunk.section_path, "") + chunk.content_hash
            )
        result[path] = per_path
    return result


async def compute_version_diff(
    session: AsyncSession,
    *,
    source_id: str,
    mirror: Path,
    from_tag: str,
    to_tag: str,
) -> VersionDiff:
    """Compute and store the diff; returns the existing row if already stored."""
    existing = await session.scalar(
        select(VersionDiff).where(
            VersionDiff.source_id == source_id,
            VersionDiff.from_tag == from_tag,
            VersionDiff.to_tag == to_tag,
        )
    )
    if existing is not None:
        return existing

    await _fetch_tag(mirror, from_tag)
    await _fetch_tag(mirror, to_tag)
    old = await _section_hashes_at(mirror, from_tag)
    new = await _section_hashes_at(mirror, to_tag)

    files_added = sorted(set(new) - set(old))
    files_removed = sorted(set(old) - set(new))
    sections_added: list[dict[str, str]] = []
    sections_removed: list[dict[str, str]] = []
    sections_changed: list[dict[str, str]] = []
    for path in sorted(set(old) & set(new)):
        old_sections, new_sections = old[path], new[path]
        for sec in sorted(set(new_sections) - set(old_sections)):
            sections_added.append({"file": path, "section": sec})
        for sec in sorted(set(old_sections) - set(new_sections)):
            sections_removed.append({"file": path, "section": sec})
        for sec in sorted(set(old_sections) & set(new_sections)):
            if old_sections[sec] != new_sections[sec]:
                sections_changed.append({"file": path, "section": sec})

    detail: dict[str, Any] = {
        "files_added": files_added,
        "files_removed": files_removed,
        "sections_added": sections_added,
        "sections_removed": sections_removed,
        "sections_changed": sections_changed,
        "summary": {
            "files_added": len(files_added),
            "files_removed": len(files_removed),
            "sections_added": len(sections_added),
            "sections_removed": len(sections_removed),
            "sections_changed": len(sections_changed),
        },
    }
    diff = VersionDiff(
        source_id=source_id,
        from_tag=from_tag,
        to_tag=to_tag,
        computed_at=datetime.now(tz=UTC),
        detail=detail,
    )
    session.add(diff)
    return diff
