---
name: support-console
description: The Technical Support Lead's fast triage surface — one query returns a grounded cited answer plus the most relevant issues/discussions (with structured summaries), a suggested playbook, and relevant glossary terms. Load this when building the support/triage endpoint or the support console UI.
---

# Support Console

The console is the support lead's single entry point for a partner question or a symptom. It is
optimized for **speed and orientation**: answer + evidence + "what else is relevant" + "what to do",
all in one structured response, all cited.

## Input
A free-text query — a partner-reported symptom, an error string, a spec question, or a vague topic
("android without google"). Optional tier/repo/version filters.

## Output (one structured packet)
1. **Answer** — grounded generation over retrieved evidence (Phase 5 rules: cite real sources only,
   explicit "not supported by sources" refusal, 8K budget). Normative-first evidence selection.
2. **Related activity** — the top issues / PRs / discussions matching the query, each with its
   **structured summary** (entity-summarization skill): tl;dr, category, status, recommended action,
   and a deep link. This is "has someone already hit this?".
3. **Suggested playbook** — if a published playbook/KB draft matches, surface it; otherwise offer to
   author one from the evidence set (grounded-authoring).
4. **Glossary** — domain terms detected in the query/answer with their definitions (semantic-recall
   skill's glossary), so an escalation can be explained to a mixed audience.

## Speed discipline
- **Never regenerate on the request path** what can be cached. Entity summaries are precomputed in the
  worker (S2); the console reads them. Only the *answer* is generated live, and only when asked.
- Run retrieval channels and related-activity lookup **in parallel**; assemble once.
- Offer a "search only" fast path (no generation) for when the lead just needs the source, and an
  "ask" path for a written answer — the UI exposes both (the existing /search and /answer already do).

## Provenance & tier honesty
- Every element carries citation + tier + last_seen.
- Issue/discussion content is **community** tier, labeled non-normative; it informs triage but never
  presented as a binding requirement. A normative question is answered from Annex 2 / specs first,
  with community activity shown as supporting context, not the answer.

## API shape (suggested)
- `POST /support/triage {query, filters?}` → `{answer, related[], playbook?, glossary[]}`.
- Reuse `/search`, `/answer`, `/dashboard/*`, `/author/*` underneath; the console composes them.

## Gate (Phase S4)
A partner-style question returns a structured packet (answer + related-with-summaries + playbook +
glossary) within the latency budget, every element cited; the UI renders it.
