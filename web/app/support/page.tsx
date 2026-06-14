"use client";

import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Citation {
  doc_title: string;
  source_url: string;
  tier: string;
  version_or_tag: string | null;
  section_heading: string;
  last_seen: string;
}
interface Summary {
  tl_dr: string;
  category: string;
  recommended_action: string;
}
interface RelatedItem {
  url: string;
  title: string;
  tier: string;
  score: number;
  summary: Summary | null;
}
interface GroundedAnswer {
  answer: string;
  insufficient_evidence: boolean;
  citations: Citation[];
}
interface Packet {
  query: string;
  answer: GroundedAnswer | null;
  related: RelatedItem[];
  playbook: { id: number; title: string; doc_type: string } | null;
  glossary: { term: string; definition: string }[];
}

export default function SupportPage() {
  const [query, setQuery] = useState("");
  const [packet, setPacket] = useState<Packet | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function triage(generate: boolean) {
    const text = query.trim();
    if (text.length < 2) return;
    setBusy(true);
    setError(null);
    setPacket(null);
    try {
      const r = await fetch(`${API_URL}/support/triage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text, generate, expand: true }),
      });
      if (!r.ok) throw new Error(`triage failed: ${r.status}`);
      setPacket((await r.json()) as Packet);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>Support console</h1>
      <p className="subtitle">
        A partner symptom or question → grounded answer, related issues already
        in the tracker, a playbook, and the terms involved.
      </p>

      <div className="searchbar">
        <div className="searchbox">
          <input
            value={query}
            placeholder="e.g. verifier rejects my presentation request"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void triage(true);
            }}
            aria-label="support query"
          />
        </div>
        <button className="btn" onClick={() => void triage(false)} disabled={busy}>
          {busy ? "…" : "Fast (no answer)"}
        </button>
        <button className="btn ask" onClick={() => void triage(true)} disabled={busy}>
          {busy ? "Triaging…" : "Triage"}
        </button>
      </div>

      {error ? <p className="detail">{error}</p> : null}

      {packet ? (
        <>
          {packet.answer ? (
            <section
              className={`panel answer ${packet.answer.insufficient_evidence ? "refused" : ""}`}
            >
              <h2 style={{ marginTop: 0 }}>
                {packet.answer.insufficient_evidence ? "No grounded answer" : "Answer"}
              </h2>
              <p style={{ whiteSpace: "pre-wrap" }}>{packet.answer.answer}</p>
              {packet.answer.citations.map((c) => (
                <div className="citation-line" key={c.source_url}>
                  <span className={`badge ${c.tier}`}>{c.tier}</span>
                  <a href={c.source_url} target="_blank" rel="noreferrer">
                    {c.doc_title} — {c.section_heading}
                  </a>
                </div>
              ))}
            </section>
          ) : null}

          {packet.playbook ? (
            <section className="panel">
              <h2 style={{ marginTop: 0 }}>Suggested playbook</h2>
              <a className="badge category" href={`/drafts/${packet.playbook.id}`}>
                {packet.playbook.doc_type}
              </a>{" "}
              <a href={`/drafts/${packet.playbook.id}`}>{packet.playbook.title}</a>
            </section>
          ) : null}

          <h2>
            Related activity <span className="count">({packet.related.length})</span>
          </h2>
          <div className="cards">
            {packet.related.map((r) => (
              <a key={r.url} className="card" href={r.url} target="_blank" rel="noreferrer">
                <div className="card-title">{r.title}</div>
                {r.summary ? (
                  <>
                    <p className="summary-tldr">{r.summary.tl_dr}</p>
                    {r.summary.recommended_action ? (
                      <p className="summary-action">
                        <strong>Action:</strong> {r.summary.recommended_action}
                      </p>
                    ) : null}
                  </>
                ) : null}
                <span className="badge community">{r.tier}</span>
                <span className="meta">score {r.score.toFixed(3)}</span>
              </a>
            ))}
            {packet.related.length === 0 ? (
              <p className="subtitle">No matching issues or discussions.</p>
            ) : null}
          </div>

          {packet.glossary.length > 0 ? (
            <div className="panel glossary-panel" style={{ marginTop: 18 }}>
              <strong>Glossary</strong>
              {packet.glossary.map((g) => (
                <div key={g.term} className="glossary-item">
                  <span className="badge category">{g.term}</span>
                  <span className="detail">{g.definition}</span>
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
