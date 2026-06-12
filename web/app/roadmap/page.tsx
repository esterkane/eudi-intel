import { formatDate, getRoadmap } from "../../lib/api";

export const dynamic = "force-dynamic";

const ORDER = ["in_progress", "planned", "completed", "other"];
const LABEL: Record<string, string> = {
  in_progress: "In progress",
  planned: "Planned",
  completed: "Completed",
  other: "Other status",
};

export default async function RoadmapPage() {
  const { items } = await getRoadmap();
  const groups = ORDER.map((m) => ({
    maturity: m,
    items: items.filter((i) => i.maturity === m),
  })).filter((g) => g.items.length > 0);

  return (
    <main>
      <h1>Roadmap &amp; Planned Work</h1>
      <p className="subtitle">
        Feature-map maturity states from the reference implementation docs.
      </p>
      {groups.map((g) => (
        <section key={g.maturity}>
          <h2>
            {LABEL[g.maturity]} <span className="count">({g.items.length})</span>
          </h2>
          <div className="cards">
            {g.items.map((i) => (
              <a key={i.title} className="card" href={i.url} target="_blank" rel="noreferrer">
                <div className="card-title">{i.title}</div>
                {i.description ? <p className="card-body">{i.description}</p> : null}
                <span className={`badge ${i.maturity}`}>{LABEL[i.maturity]}</span>
                <div className="meta">last seen {formatDate(i.last_seen)}</div>
              </a>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}
