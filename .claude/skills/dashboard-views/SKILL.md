---
name: dashboard-views
description: The four specific live dashboard views (Latest Releases / What Changed, Roadmap & Planned Work, Open Issues & Feature Requests, Current Activity) — exactly where each card's data comes from and where it clicks through to. Load this when building the dashboard or its backing endpoints.
---

# Dashboard — four live views (not generic analytics)

The dashboard is backed by normalized entities, not raw crawled blobs. Build exactly these
four views. Every card must click through to its primary source. Use the `frontend-design`
public skill for the styling pass; use Next.js server components for SSR.

## 1. Latest Releases & What Changed
- **Data:** Release entities from `releases.atom` feeds + computed version diffs (ingestion
  Phase 2/8). E.g. an ARF release entry, reference-implementation release notes (OID4VCI/OID4VP/HAIP
  alignment, Wallet Unit/Instance Attestation), and the section-level diff vs the prior version.
- **Card → click-through:** the release URL and/or the version-diff detail (sections added/changed/removed).

## 2. Roadmap & Planned Work
- **Data:** RoadmapItem entities from the reference-implementation roadmap repo + the feature map
  maturity states + the STS roadmap. Show open items (e.g. Wallet Instance Attestation integration,
  trust-list wallet integration, alignment with amended implementing acts, Digital Credential API
  presentation, conformance coverage) and maturity (completed / in-progress / planned).
- **Card → click-through:** the roadmap item / repo issue / feature-map entry URL.

## 3. Open Issues & Feature Requests
- **Data:** Issue + PullRequest entities from the scrape collector (HTML list pages in token-free
  mode; REST if a token is later added). Title, number, state, labels, updated_at.
- **Card → click-through:** the issue/PR URL.

## 4. Current Activity
- **Data:** synthesized from recently-updated PRs, issues, discussions, and conformance-draft
  changes (e.g. new OpenID4VP / Token Status List / PID data-model test cases from
  conformance.eudi.dev). Sort by recency.
- **Card → click-through:** the underlying PR/issue/discussion/conformance-changelog URL.

## Cross-cutting requirements
- **Tier badges:** show authority tier on items where relevant; mark community/discussion as
  non-normative background.
- **Freshness:** show `last_seen`/`updated_at` on every card; the dashboard's job is "what changed"
  and "what's active now".
- **No card without a source link.** If an item lacks a primary URL, it doesn't belong on the board.
- **Backed by endpoints:** e.g. `GET /dashboard/releases`, `/dashboard/roadmap`, `/dashboard/issues`,
  `/dashboard/activity`. Each returns normalized entities with source URLs + timestamps + tier.

## Gate (Phase 6)
All four views render from live ingested data and every card click-throughs to its primary source.
