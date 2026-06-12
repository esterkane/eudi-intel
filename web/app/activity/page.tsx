import { formatDate, getActivity } from "../../lib/api";

export const dynamic = "force-dynamic";

const KIND_LABEL: Record<string, string> = {
  issue: "issue",
  pull_request: "PR",
  discussion: "discussion",
  release: "release",
};

export default async function ActivityPage() {
  const { items } = await getActivity();
  return (
    <main>
      <h1>Current Activity</h1>
      <p className="subtitle">
        Recently updated issues, pull requests, discussions and releases,
        newest first.
      </p>
      <div className="activity-list">
        {items.map((item) => (
          <a
            key={item.url + item.timestamp}
            className="card row-card"
            href={item.url}
            target="_blank"
            rel="noreferrer"
          >
            <span className={`badge kind-${item.kind}`}>{KIND_LABEL[item.kind] ?? item.kind}</span>
            <span className="card-title">{item.title}</span>
            <span className={`badge ${item.tier}`}>{item.tier}</span>
            <span className="meta">{formatDate(item.timestamp)}</span>
          </a>
        ))}
      </div>
    </main>
  );
}
