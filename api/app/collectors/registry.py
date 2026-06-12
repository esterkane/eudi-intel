"""Canonical EUDI source registry, modelled as data (eudi-source-registry skill).

Collectors and the Phase 2 tiering step read from this one place. URLs and
default branches were verified live on 2026-06-12 (git ls-remote + HTTP probes;
the EC page URL is the post-redirect canonical form).

Tier rules (CLAUDE.md): the ARF repo carries reference tier here at source level;
Annex 2 inside it is promoted to normative at parse time (Phase 2), because the
normative boundary is per-document, not per-repo. Discussion/issue/PR content is
always community and never normative.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.source import FetchMethod, Tier

_ORG = "https://github.com/eu-digital-identity-wallet"
_ARF = f"{_ORG}/eudi-doc-architecture-and-reference-framework"
_STS = f"{_ORG}/eudi-doc-standards-and-technical-specifications"
_API = "https://api.github.com/repos/eu-digital-identity-wallet"
_ARF_API = f"{_API}/eudi-doc-architecture-and-reference-framework"


class SourceSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    tier: Tier
    method: FetchMethod
    url: str
    # Authenticated REST equivalent, used only when GITHUB_TOKEN is set
    # (clean strategy switch per CLAUDE.md; default off).
    api_url: str | None = None


REGISTRY: tuple[SourceSpec, ...] = (
    # ── Document corpus via git (no REST, no rate limit) ────────────────────
    SourceSpec(
        id="arf_repo",
        title="ARF — architecture & reference framework repo (narrative, annexes, discussions)",
        tier=Tier.reference,
        method=FetchMethod.git,
        url=f"{_ARF}.git",
    ),
    SourceSpec(
        id="sts_repo",
        title="Standards & Technical Specifications (STS) repo",
        tier=Tier.roadmap,
        method=FetchMethod.git,
        url=f"{_STS}.git",
    ),
    # ── Release / tag / commit activity via Atom feeds ───────────────────────
    SourceSpec(
        id="arf_releases_feed",
        title="ARF releases (atom)",
        tier=Tier.roadmap,
        method=FetchMethod.feed,
        url=f"{_ARF}/releases.atom",
        api_url=f"{_ARF_API}/releases?per_page=30",
    ),
    SourceSpec(
        id="arf_tags_feed",
        title="ARF tags (atom)",
        tier=Tier.roadmap,
        method=FetchMethod.feed,
        url=f"{_ARF}/tags.atom",
        api_url=f"{_ARF_API}/tags?per_page=30",
    ),
    SourceSpec(
        id="arf_commits_feed",
        title="ARF commits on main (atom)",
        tier=Tier.roadmap,
        method=FetchMethod.feed,
        url=f"{_ARF}/commits/main.atom",
        api_url=f"{_ARF_API}/commits?sha=main&per_page=30",
    ),
    SourceSpec(
        id="sts_releases_feed",
        title="STS releases (atom)",
        tier=Tier.roadmap,
        method=FetchMethod.feed,
        url=f"{_STS}/releases.atom",
    ),
    # ── Rendered docs / sites via crawl ──────────────────────────────────────
    SourceSpec(
        id="eudi_dev_latest",
        title="eudi.dev — rendered ARF docs (latest)",
        tier=Tier.reference,
        method=FetchMethod.crawl,
        url="https://eudi.dev/latest/",
    ),
    SourceSpec(
        id="refimpl_roadmap",
        title="Reference implementation roadmap",
        tier=Tier.roadmap,
        method=FetchMethod.crawl,
        url="https://docs.eudi.dev/latest/reference-implementation/roadmap/",
    ),
    SourceSpec(
        id="refimpl_repos_list",
        title="Reference implementation repositories list",
        tier=Tier.roadmap,
        method=FetchMethod.crawl,
        url="https://docs.eudi.dev/latest/reference-implementation/repositories-list/",
    ),
    SourceSpec(
        id="conformance_site",
        title="Functional Conformance Assessment Framework",
        tier=Tier.reference,
        method=FetchMethod.crawl,
        url="https://conformance.eudi.dev/",
    ),
    SourceSpec(
        id="ec_policy_page",
        title="European Commission — European Digital Identity policy page",
        tier=Tier.reference,
        method=FetchMethod.crawl,
        url=(
            "https://commission.europa.eu/topics/digital-economy-and-society/"
            "european-digital-identity_en"
        ),
    ),
    # ── Issue / PR / discussion activity via HTML scrape ─────────────────────
    SourceSpec(
        id="arf_issues",
        title="ARF open issues (list page)",
        tier=Tier.community,
        method=FetchMethod.scrape,
        url=f"{_ARF}/issues",
        api_url=f"{_ARF_API}/issues?state=open&per_page=100",
    ),
    SourceSpec(
        id="arf_pulls",
        title="ARF open pull requests (list page)",
        tier=Tier.community,
        method=FetchMethod.scrape,
        url=f"{_ARF}/pulls",
        api_url=f"{_ARF_API}/pulls?state=open&per_page=100",
    ),
    SourceSpec(
        id="arf_discussions",
        title="ARF discussions (list page)",
        tier=Tier.community,
        method=FetchMethod.scrape,
        url=f"{_ARF}/discussions",
    ),
)


def get_source(source_id: str) -> SourceSpec | None:
    for spec in REGISTRY:
        if spec.id == source_id:
            return spec
    return None
