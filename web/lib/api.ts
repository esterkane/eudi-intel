// Server-component data access. Inside the compose network the web container
// reaches the API at API_INTERNAL_URL (http://api:8000); the browser-facing
// NEXT_PUBLIC_API_URL is the fallback for local dev outside Docker.

const API_BASE =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export interface EntitySummary {
  tl_dr: string;
  category: string;
  components: string[];
  what: string;
  why: string;
  status: string;
  recommended_action: string;
  non_normative: boolean;
}

export interface ReleaseCard {
  title: string;
  url: string;
  source_id: string;
  published_at: string | null;
  summary: EntitySummary | null;
}

export interface DiffCard {
  source_id: string;
  from_tag: string;
  to_tag: string;
  computed_at: string;
  summary: Record<string, number>;
  sections_changed: { file: string; section: string }[];
}

export interface ReleasesView {
  releases: ReleaseCard[];
  diffs: DiffCard[];
}

export interface RoadmapCard {
  title: string;
  description: string | null;
  maturity: string;
  url: string;
  last_seen: string;
}

export interface GithubItemCard {
  kind: string;
  repo: string;
  number: number;
  title: string;
  state: string;
  url: string;
  updated_at: string | null;
  last_seen: string;
  summary: EntitySummary | null;
}

export interface IssuesView {
  issues: GithubItemCard[];
  pull_requests: GithubItemCard[];
}

export interface ActivityItem {
  kind: string;
  title: string;
  url: string;
  timestamp: string;
  tier: string;
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`API ${path} responded ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export const getReleases = () => getJson<ReleasesView>("/dashboard/releases");
export const getRoadmap = () => getJson<{ items: RoadmapCard[] }>("/dashboard/roadmap");
export const getIssues = () => getJson<IssuesView>("/dashboard/issues");
export const getActivity = () => getJson<{ items: ActivityItem[] }>("/dashboard/activity");

export function formatDate(iso: string | null): string {
  if (!iso) return "n/a";
  return new Date(iso).toISOString().slice(0, 10);
}
