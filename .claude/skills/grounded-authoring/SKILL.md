---
name: grounded-authoring
description: The authoring plane — generating FAQs, troubleshooting playbooks, and KB articles from a selected evidence set, with citation/version-stamp inheritance, a "source basis" record, and a human finalize/publish gate. Load this when building authoring endpoints or the authoring UI.
---

# Grounded Authoring

Authoring is **evidence-backed drafting, not autonomous authorship**. The user selects an
evidence set (from search results); the app generates a structured draft where every section
inherits the provenance of its source chunks. A human must finalize before anything is "published".

This discipline matters because some EUDI sources are live roadmaps and others are explicitly
non-normative or subject to change — a draft must always show what it stands on.

## Inputs
- A selected **evidence set**: the retrieved chunks the user chose (each already carries
  `doc_title, source_url, tier, version_or_tag, section_heading, last_seen`).
- A **document type**: `faq` | `playbook` | `kb_article`.

## Generation rules
- Generate with `qwen3:8b`, constrained to the provided evidence — no outside facts.
- **Citation inheritance:** every generated section/answer carries the citations and version
  stamps of the chunks it was derived from. Do not emit a claim without an inherited citation.
- **Tier awareness:** if a section leans on community/discussion or STS (subject-to-change)
  content, label it non-normative in the draft.
- **Structure per type:**
  - `faq` — Q/A pairs; each answer cites its source(s).
  - `playbook` — symptom → diagnosis → steps → references; steps trace to source chunks.
  - `kb_article` — title, summary, body sections, references; each section cites sources.

## Source basis (attach to every draft)
A `GeneratedDraft` stores a **source_basis**: the full evidence set used, with each item's
tier/version/last_seen, plus the model + timestamp. This is the audit trail for the draft.

## Publish gate (do NOT auto-publish)
- A draft is created in `status=draft` with source_basis attached.
- It can only become `status=published` via an explicit human **finalize** action in the UI.
- On finalize, re-affirm citations are intact; optionally re-check that cited sources haven't
  changed `version_or_tag`/`last_seen` since drafting, and warn if they have.

## API shape (suggested)
- `POST /author/draft` `{type, evidence_ids[]}` → GeneratedDraft with sections + inherited citations + source_basis.
- `POST /author/finalize/{draft_id}` → sets published (human action).
- `GET /author/drafts` / `GET /author/draft/{id}` → review.

## Gate (Phase 7)
A generated draft shows per-section provenance (citations + version stamps), carries a source_basis,
and cannot be published without an explicit finalize action.
