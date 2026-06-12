"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Component = { status: string; detail: string };
type Health = { status: string; components: Record<string, Component> };

export default function HealthStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/health`, { cache: "no-store" })
      .then((r) => r.json() as Promise<Health>)
      .then(setHealth)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="panel">
        <div className="row">
          <span className="name">API unreachable</span>
          <span className="badge error">error</span>
        </div>
        <p className="detail">
          Could not reach {API_URL}/health — is the api service up?
        </p>
      </div>
    );
  }

  if (!health) {
    return (
      <div className="panel">
        <p className="detail">Checking system health…</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="row">
        <span className="name">Overall</span>
        <span className={`badge ${health.status === "ok" ? "ok" : "error"}`}>
          {health.status}
        </span>
      </div>
      {Object.entries(health.components).map(([name, c]) => (
        <div className="row" key={name}>
          <div>
            <div className="name">{name}</div>
            <div className="detail">{c.detail}</div>
          </div>
          <span className={`badge ${c.status}`}>{c.status}</span>
        </div>
      ))}
    </div>
  );
}
