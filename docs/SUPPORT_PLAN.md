# SUPPORT_PLAN.md — Technical Support Lead capability track (phases S1–S4)

The workbench has a second audience: the **EUDI-Wallet Technical Support Lead** (SPRIND).
Its "customers" are B2B ecosystem partners — credential **providers** and **verifiers**
integrating against the wallet, the ARF, and the reference implementations. The lead:

- triages integration errors and API/protocol issues (OAuth/OIDC, OID4VP/OID4VCI, eIDAS 2.0),
- finds the relevant spec section / issue / discussion **fast**, often from a vague symptom
  rather than the exact keyword ("android without google", "verifier gets invalid_request"),
- explains complexity to mixed audiences and writes troubleshooting playbooks + integration guides,
- turns partner feedback into product insight.

These phases layer those loops onto the v1 intelligence workbench. The v1 rules still bind:
**token-free** GitHub access, **GPU = LLM only** (embed/rerank on CPU), and **provenance**
(citation + tier + last_seen) on everything.

---

### Phase S1 — Deep activity ingestion (issue / PR / discussion bodies)
The support gold — the *body* of an issue and its discussion thread — is not searchable today:
only titles/metadata are stored. Scrape each item's page (token-free HTML), extract the body +
visible comments (Trafilatura), store as a **community-tier** Document/Section keyed by the item
URL, and embed it. On-demand (open one) + batch (recently-active top-N) + cadence.
- **Gate:** the body text of a known issue is semantically retrievable via `/search`; re-ingest is
  idempotent (dedupe by url + content_hash); runs token-free.

### Phase S2 — Structured entity summaries
For every Issue / PR / Discussion / Release, a cached, grounded, schema'd summary:
`{tl_dr, category, components[], what, why, status, recommended_action, non_normative}`.
Generated in the worker, regenerated only on content-hash change, shown on dashboard cards and
search results so a card tells you **exactly what it is about** at a glance.
- **Gate:** sampled issue/release cards show a structured summary derived from real ingested
  content; missing content → explicit "insufficient detail" (never invented); regenerates on change.

### Phase S3 — Semantic recall + query expansion + domain glossary
A domain glossary / alias map (eIDAS 2.0 + EUDI jargon: de-Googled / GMS-less / AOSP / GrapheneOS,
WUA, PID, rQES, OID4VP/OID4VCI, LoA, RP, …) plus **LLM query expansion** (HyDE-lite) so vague
symptom queries retrieve the right material. Expansion feeds the existing hybrid pipeline; it does
not replace it.
- **Gate:** a recall eval set of vague→expected queries — including "android os without google" →
  de-Googled / AOSP / GMS content — meets a recall@10 threshold, and exact-keyword queries do not
  regress.

### Phase S4 — Support console
One surface: a query → grounded cited **answer** + ranked **related issues/discussions** (with their
S2 summaries) + a **suggested playbook** + relevant **glossary** terms, assembled fast (parallel
retrieval + summary cache, never blocking on cold generation when a cached summary exists). Adds an
`integration_guide` authoring type.
- **Gate:** a partner-style question returns a structured support packet (answer + related + playbook)
  within a set latency budget, every element carrying provenance; the UI renders it.

---

## Cross-cutting acceptance
- **Token-free**, **GPU = LLM only**, **provenance everywhere** — unchanged from v1.
- **Speed:** cache summaries and query expansions; precompute in the worker; the console must serve a
  cached summary instantly rather than regenerate on the request path.
- **Tier honesty:** issue/discussion content is community tier and labeled non-normative; it never
  outranks an Annex 2 / spec answer on a normative question.
