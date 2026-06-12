import { formatDate, getReleases } from "../../lib/api";

export const dynamic = "force-dynamic";

export default async function ReleasesPage() {
  const { releases, diffs } = await getReleases();
  return (
    <main>
      <h1>Latest Releases &amp; What Changed</h1>
      <p className="subtitle">
        Release entities from the GitHub atom feeds plus computed section-level
        version diffs.
      </p>

      <h2>What changed</h2>
      <div className="cards">
        {diffs.map((d) => (
          <a
            key={`${d.source_id}-${d.from_tag}-${d.to_tag}`}
            className="card"
            href={`https://github.com/eu-digital-identity-wallet/eudi-doc-architecture-and-reference-framework/compare/${d.from_tag}...${d.to_tag}`}
            target="_blank"
            rel="noreferrer"
          >
            <div className="card-title">
              {d.source_id}: {d.from_tag} → {d.to_tag}
            </div>
            <div className="diff-stats">
              <span className="stat add">+{d.summary.sections_added ?? 0} sections</span>
              <span className="stat del">−{d.summary.sections_removed ?? 0}</span>
              <span className="stat chg">~{d.summary.sections_changed ?? 0} changed</span>
              <span className="stat">+{d.summary.files_added ?? 0} files</span>
            </div>
            <ul className="diff-list">
              {d.sections_changed.slice(0, 6).map((s, i) => (
                <li key={i}>{s.section}</li>
              ))}
            </ul>
            <div className="meta">computed {formatDate(d.computed_at)}</div>
          </a>
        ))}
      </div>

      <h2>Releases</h2>
      <div className="cards">
        {releases.map((r) => (
          <a key={r.url} className="card" href={r.url} target="_blank" rel="noreferrer">
            <div className="card-title">{r.title}</div>
            <span className="badge roadmap">{r.source_id}</span>
            <div className="meta">published {formatDate(r.published_at)}</div>
          </a>
        ))}
      </div>
    </main>
  );
}
