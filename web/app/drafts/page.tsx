import Link from "next/link";
import { formatDate } from "../../lib/api";

export const dynamic = "force-dynamic";

const API_BASE =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

interface DraftSummary {
  id: number;
  doc_type: string;
  title: string;
  status: string;
  created_at: string;
  sections: number;
}

export default async function DraftsPage() {
  const resp = await fetch(`${API_BASE}/author/drafts`, { cache: "no-store" });
  const drafts = (await resp.json()) as DraftSummary[];
  return (
    <main>
      <h1>Authored Drafts</h1>
      <p className="subtitle">
        Evidence-backed drafts. A draft only becomes published through the
        explicit finalize action — never automatically.
      </p>
      <div className="cards">
        {drafts.map((d) => (
          <Link key={d.id} className="card" href={`/drafts/${d.id}`}>
            <div className="card-title">{d.title}</div>
            <span className={`badge ${d.status === "published" ? "completed" : "planned"}`}>
              {d.status}
            </span>
            <span className="badge community">{d.doc_type}</span>
            <div className="meta">
              {d.sections} sections · created {formatDate(d.created_at)}
            </div>
          </Link>
        ))}
        {drafts.length === 0 ? (
          <p className="subtitle">No drafts yet — create one via POST /author/draft.</p>
        ) : null}
      </div>
    </main>
  );
}
