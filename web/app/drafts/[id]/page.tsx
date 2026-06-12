import { formatDate } from "../../../lib/api";
import FinalizeButton from "./FinalizeButton";

export const dynamic = "force-dynamic";

const API_BASE =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

interface Citation {
  doc_title: string;
  source_url: string;
  tier: string;
  version_or_tag: string | null;
  section_heading: string;
  last_seen: string;
}

interface DraftSection {
  heading: string;
  content: string;
  citations: Citation[];
  non_normative: boolean;
  uncited: boolean;
}

interface Draft {
  id: number;
  doc_type: string;
  title: string;
  status: string;
  created_at: string;
  finalized_at: string | null;
  sections: DraftSection[];
  source_basis: {
    model: string;
    generated_at: string;
    evidence: Citation[];
  };
}

export default async function DraftPage({
  params,
}: {
  params: { id: string };
}) {
  const resp = await fetch(`${API_BASE}/author/draft/${params.id}`, {
    cache: "no-store",
  });
  if (!resp.ok) {
    return (
      <main>
        <h1>Draft not found</h1>
      </main>
    );
  }
  const draft = (await resp.json()) as Draft;
  return (
    <main>
      <h1>{draft.title}</h1>
      <p className="subtitle">
        <span className={`badge ${draft.status === "published" ? "completed" : "planned"}`}>
          {draft.status}
        </span>
        <span className="badge community">{draft.doc_type}</span>
        {draft.finalized_at ? ` finalized ${formatDate(draft.finalized_at)}` : null}
      </p>
      {draft.status === "draft" ? <FinalizeButton draftId={draft.id} /> : null}

      {draft.sections.map((s, i) => (
        <section key={i} className="panel" style={{ marginBottom: 14 }}>
          <h2 style={{ marginTop: 0 }}>{s.heading}</h2>
          {s.non_normative ? (
            <span className="badge community">non-normative basis</span>
          ) : null}
          {s.uncited ? <span className="badge error">uncited</span> : null}
          <p style={{ whiteSpace: "pre-wrap" }}>{s.content}</p>
          <div className="meta">
            {s.citations.map((c) => (
              <div key={c.source_url}>
                [{c.tier}] <a href={c.source_url}>{c.doc_title} — {c.section_heading}</a>{" "}
                (v: {c.version_or_tag ?? "n/a"}, seen {formatDate(c.last_seen)})
              </div>
            ))}
          </div>
        </section>
      ))}

      <h2>Source basis</h2>
      <div className="panel">
        <div className="meta">
          model {draft.source_basis.model} · generated{" "}
          {formatDate(draft.source_basis.generated_at)}
        </div>
        {draft.source_basis.evidence.map((c) => (
          <div className="row" key={c.source_url}>
            <span className="detail">
              <a href={c.source_url}>{c.doc_title} — {c.section_heading}</a>
            </span>
            <span className={`badge ${c.tier}`}>{c.tier}</span>
          </div>
        ))}
      </div>
    </main>
  );
}
