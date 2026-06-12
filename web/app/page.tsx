import Link from "next/link";
import HealthStatus from "./HealthStatus";

const VIEWS = [
  {
    href: "/releases",
    title: "Releases & What Changed",
    body: "ARF releases and section-level version diffs.",
  },
  {
    href: "/roadmap",
    title: "Roadmap & Planned Work",
    body: "Feature-map maturity: completed, in progress, planned.",
  },
  {
    href: "/issues",
    title: "Open Issues & Feature Requests",
    body: "Live issue and PR activity from the ARF repo.",
  },
  {
    href: "/activity",
    title: "Current Activity",
    body: "Most recently updated items across all sources.",
  },
];

export default function Home() {
  return (
    <main>
      <h1>EUDI Intelligence &amp; Authoring Workbench</h1>
      <p className="subtitle">
        Local, citation-first intelligence for the EU Digital Identity
        ecosystem.
      </p>
      <div className="home-links">
        {VIEWS.map((v) => (
          <Link key={v.href} href={v.href} className="card">
            <div className="card-title">{v.title}</div>
            <p className="card-body">{v.body}</p>
          </Link>
        ))}
      </div>
      <h2>System health</h2>
      <HealthStatus />
    </main>
  );
}
