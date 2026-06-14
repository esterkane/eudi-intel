import { formatDate, getIssues, type GithubItemCard } from "../../lib/api";
import SummaryBlock from "../Summary";

export const dynamic = "force-dynamic";

function ItemCard({ item }: { item: GithubItemCard }) {
  return (
    <a className="card" href={item.url} target="_blank" rel="noreferrer">
      <div className="card-title">
        #{item.number} {item.title}
      </div>
      <SummaryBlock summary={item.summary} />
      <span className="badge community">community</span>
      <span className={`badge state-${item.state}`}>{item.state}</span>
      <div className="meta">
        updated {formatDate(item.updated_at)} · seen {formatDate(item.last_seen)}
      </div>
    </a>
  );
}

export default async function IssuesPage() {
  const { issues, pull_requests } = await getIssues();
  return (
    <main>
      <h1>Open Issues &amp; Feature Requests</h1>
      <p className="subtitle">
        Scraped from the GitHub list pages (token-free) — community tier,
        non-normative by definition.
      </p>
      <h2>
        Open issues <span className="count">({issues.length})</span>
      </h2>
      <div className="cards">
        {issues.map((i) => (
          <ItemCard key={`${i.repo}#${i.number}`} item={i} />
        ))}
      </div>
      <h2>
        Open pull requests <span className="count">({pull_requests.length})</span>
      </h2>
      <div className="cards">
        {pull_requests.map((p) => (
          <ItemCard key={`${p.repo}#${p.number}`} item={p} />
        ))}
      </div>
    </main>
  );
}
