"use client";

import { useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Citation {
  doc_title: string;
  source_url: string;
  tier: string;
  version_or_tag: string | null;
  section_heading: string;
  last_seen: string;
}

interface SearchHit {
  score: number;
  content: string;
  section_path: string;
  citation: Citation;
}

interface Suggestion {
  text: string;
  kind: string;
  url: string;
  similarity: number;
}

interface GroundedAnswer {
  answer: string;
  insufficient_evidence: boolean;
  citations: Citation[];
  invalid_markers: number[];
  evidence: { index: number; citation: Citation; content: string }[];
}

function date(iso: string): string {
  return iso.slice(0, 10);
}

function CitationLine({ c }: { c: Citation }) {
  return (
    <div className="citation-line">
      <span className={`badge ${c.tier}`}>{c.tier}</span>
      <a href={c.source_url} target="_blank" rel="noreferrer">
        {c.doc_title} — {c.section_heading}
      </a>
      <span className="meta">
        v: {c.version_or_tag ?? "n/a"} · seen {date(c.last_seen)}
      </span>
    </div>
  );
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [answer, setAnswer] = useState<GroundedAnswer | null>(null);
  const [expand, setExpand] = useState(false);
  const [glossary, setGlossary] = useState<{ term: string; definition: string }[]>([]);
  const [searching, setSearching] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    if (query.trim().length < 3) {
      setSuggestions([]);
      return;
    }
    debounce.current = setTimeout(async () => {
      try {
        const r = await fetch(
          `${API_URL}/suggest?q=${encodeURIComponent(query)}&limit=6`
        );
        if (r.ok) {
          const body = (await r.json()) as { suggestions: Suggestion[] };
          setSuggestions(body.suggestions);
        }
      } catch {
        setSuggestions([]);
      }
    }, 250);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [query]);

  async function runSearch(q?: string) {
    const text = (q ?? query).trim();
    if (text.length < 2) return;
    setSearching(true);
    setError(null);
    setSuggestions([]);
    setAnswer(null);
    try {
      const params = new URLSearchParams({ q: text, limit: "10" });
      if (tier) params.set("tier", tier);
      if (expand) params.set("expand", "true");
      const r = await fetch(`${API_URL}/search?${params}`);
      if (!r.ok) throw new Error(`search failed: ${r.status}`);
      const body = (await r.json()) as {
        results: SearchHit[];
        glossary?: { term: string; definition: string }[];
      };
      setHits(body.results);
      setGlossary(body.glossary ?? []);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setSearching(false);
    }
  }

  async function runAsk() {
    const text = query.trim();
    if (text.length < 2) return;
    setAsking(true);
    setError(null);
    setSuggestions([]);
    try {
      const r = await fetch(`${API_URL}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text, tier: tier || null }),
      });
      if (!r.ok) throw new Error(`answer failed: ${r.status}`);
      setAnswer((await r.json()) as GroundedAnswer);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setAsking(false);
    }
  }

  return (
    <main>
      <h1>Search the EUDI corpus</h1>
      <p className="subtitle">
        Hybrid retrieval (lexical + dense + sparse, reranked) with mandatory
        citations — or ask for a grounded answer.
      </p>

      <div className="searchbar">
        <div className="searchbox">
          <input
            value={query}
            placeholder="e.g. wallet unit attestation revocation"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSearch();
            }}
            aria-label="search query"
          />
          {suggestions.length > 0 ? (
            <ul className="suggest-list" role="listbox">
              {suggestions.map((s) => (
                <li key={`${s.kind}-${s.text}`}>
                  <button
                    onClick={() => {
                      setQuery(s.text);
                      void runSearch(s.text);
                    }}
                  >
                    <span className="badge community">{s.kind}</span>
                    {s.text}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <select value={tier} onChange={(e) => setTier(e.target.value)} aria-label="tier filter">
          <option value="">all tiers</option>
          <option value="normative">normative</option>
          <option value="reference">reference</option>
          <option value="roadmap">roadmap</option>
          <option value="community">community</option>
        </select>
        <button className="btn" onClick={() => void runSearch()} disabled={searching}>
          {searching ? "Searching…" : "Search"}
        </button>
        <button className="btn ask" onClick={() => void runAsk()} disabled={asking}>
          {asking ? "Thinking…" : "Ask"}
        </button>
      </div>

      <label className="expand-toggle">
        <input
          type="checkbox"
          checked={expand}
          onChange={(e) => setExpand(e.target.checked)}
        />
        Expand recall (glossary + HyDE) — for vague queries when you’re unsure of the exact term
      </label>

      {glossary.length > 0 ? (
        <div className="panel glossary-panel">
          <strong>Glossary</strong>
          {glossary.map((g) => (
            <div key={g.term} className="glossary-item">
              <span className="badge category">{g.term}</span>
              <span className="detail">{g.definition}</span>
            </div>
          ))}
        </div>
      ) : null}

      {error ? <p className="detail">{error}</p> : null}

      {answer ? (
        <section className={`panel answer ${answer.insufficient_evidence ? "refused" : ""}`}>
          <h2 style={{ marginTop: 0 }}>
            {answer.insufficient_evidence ? "No grounded answer" : "Grounded answer"}
          </h2>
          <p style={{ whiteSpace: "pre-wrap" }}>{answer.answer}</p>
          {answer.citations.length > 0 ? (
            <div>
              {answer.citations.map((c) => (
                <CitationLine key={c.source_url} c={c} />
              ))}
            </div>
          ) : null}
          {answer.invalid_markers.length > 0 ? (
            <p className="detail">
              dropped fabricated markers: {answer.invalid_markers.join(", ")}
            </p>
          ) : null}
        </section>
      ) : null}

      {hits !== null ? (
        <section>
          <h2>
            Results <span className="count">({hits.length})</span>
          </h2>
          {hits.length === 0 ? <p className="subtitle">No results.</p> : null}
          <div className="results">
            {hits.map((h) => (
              <div className="panel result" key={h.citation.source_url + h.score}>
                <CitationLine c={h.citation} />
                <p className="result-snippet">{h.content.slice(0, 420)}…</p>
                <div className="meta">
                  score {h.score.toFixed(3)} · {h.section_path}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  );
}
