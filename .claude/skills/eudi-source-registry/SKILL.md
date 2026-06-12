---
name: eudi-source-registry
description: Canonical registry of EUDI sources — their authority tier, URLs/repos, the exact token-free fetch method for each, and the freshness policy. Load this when implementing collectors, assigning tiers, or deciding how to fetch a given source.
---

# EUDI Source Registry

The app must NOT flatten EUDI content into one undifferentiated corpus. Every source has an
**authority tier** and a **fetch method**. Model this registry as data (DB table or config)
so collectors and the tiering step read from one place.

## Authority tiers (ranking order)
1. **normative** — latest ARF **Annex 2** + formal technical specifications. The normative
   high-level requirements. Outranks all else.
2. **reference** — ARF main narrative + other annexes (ecosystem roles, high-level architecture,
   trust, certification, accessibility, document development, references) + technical specs.
3. **roadmap** — reference-implementation roadmap, feature map, STS standards roadmap, releases.
4. **community** — discussion papers, issues, PR threads. Always labeled non-normative.

Rule from the ARF itself: once a discussion paper is integrated into the ARF it may become
outdated; the final requirements are those in the latest Annex 2. The STS repo is explicitly
informational and subject to change. Encode that: discussion/STS content is never normative.

## Sources and fetch methods (token-free)
> `repo` = git clone/pull (no API). `feed` = GitHub Atom (releases/tags/commits). `crawl` =
> httpx+Trafilatura (Playwright fallback). `scrape` = HTML list-page scrape. Verify exact paths
> at build time by cloning each repo into `reference/` and inspecting structure.

| Source | Tier | Method | Location |
|---|---|---|---|
| ARF — main narrative & chapters | reference | repo + crawl | `eu-digital-identity-wallet/eudi-doc-architecture-and-reference-framework` ; rendered: `eudi.dev/latest/...` |
| ARF — Annex 2 (normative HL requirements) | **normative** | repo + crawl | same repo, `/annexes/` ; treat Annex 2 as top tier |
| ARF — other annexes | reference | repo + crawl | same repo `/annexes/` |
| ARF — discussion topics/papers | community | repo | same repo discussion dirs; label non-normative |
| ARF — releases & tags (SemVer) | roadmap | feed | `.../eudi-doc-architecture-and-reference-framework/releases.atom`, `/tags.atom` |
| Versioned ARF docs (pinned) | reference | crawl | `eudi.dev/2.7.3/...` and `eudi.dev/latest/...` |
| Standards & Technical Specs (STS) roadmap | roadmap | repo + feed | the STS repo; informational, subject to change |
| Reference-implementation roadmap | roadmap | repo + crawl | `docs.eudi.dev/latest/reference-implementation/roadmap/` |
| Reference-implementation repositories list | roadmap | crawl | `docs.eudi.dev/latest/reference-implementation/repositories-list/` |
| Reference-implementation releases | roadmap | feed | each ref-impl repo `releases.atom` |
| Functional Conformance Assessment Framework | reference | crawl | `conformance.eudi.dev/` (test suites, changelog of new test cases) |
| EC EUDI policy page | reference | crawl | the European Commission EUDI page |
| Issues / PRs / discussions (activity) | community | scrape | HTML list pages of the repos above |

Notes:
- The "what are developers working on?" signal = reference-implementation roadmap open items
  (e.g. Wallet Instance Attestation integration, trust-list integration, alignment with amended
  implementing acts, Digital Credential API presentation, conformance coverage) + the feature
  map maturity states (completed / in-progress / planned). Capture maturity state per RoadmapItem.
- The conformance site publishes a draft changelog (new OpenID4VP / Token Status List / PID
  data-model test cases). Treat changelog entries as "what changed" activity signals.

## Freshness policy
- **Latest-only index** for operational search; **history index** for "what changed between versions".
- Because the ARF uses SemVer and is a regularly updated GitHub doc, when a new tag appears,
  trigger targeted re-ingestion of that version and compute a diff.
- Poll cadence lives in `.env` (feeds ~3h, scrape ~6h, crawl daily, git pull ~12h).

## Tiering implementation
- Assign tier by source rule at ingest, not by guesswork. Store `tier` on Document and propagate
  to every Section and every Qdrant payload.
- Surface tier in search results and citations so a reviewer can see normative vs background at a glance.
