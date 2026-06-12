"""git collector — clone --depth 1 / fetch a repo mirror (no REST, no rate limit).

The repo content itself is consumed by Phase 2 parsers from the mirror directory;
the snapshot records the HEAD commit as the content hash so re-runs without new
commits dedupe cleanly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.collectors.base import CollectResult
from app.collectors.registry import SourceSpec


class GitCollectorError(RuntimeError):
    pass


async def run_git(*args: str, cwd: Path | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise GitCollectorError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): {stderr.decode(errors='replace').strip()}"
        )
    return stdout.decode(errors="replace").strip()


async def collect_git(spec: SourceSpec, repos_dir: Path) -> CollectResult:
    """Clone the repo on first run, fetch+fast-forward afterwards; snapshot = HEAD sha."""
    mirror = repos_dir / spec.id
    if not (mirror / ".git").exists():
        repos_dir.mkdir(parents=True, exist_ok=True)
        await run_git("clone", "--depth", "1", spec.url, str(mirror))
    else:
        await run_git("fetch", "--depth", "1", "origin", cwd=mirror)
        await run_git("reset", "--hard", "origin/HEAD", cwd=mirror)

    head = await run_git("rev-parse", "HEAD", cwd=mirror)
    branch = await run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=mirror)
    return CollectResult(
        source_id=spec.id,
        url=spec.url,
        status="fetched",
        content_hash=head,
        payload=f"HEAD={head} branch={branch}",
        payload_ref=str(mirror),
    )
