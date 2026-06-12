"use client";

import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function FinalizeButton({ draftId }: { draftId: number }) {
  const [busy, setBusy] = useState(false);
  const [warnings, setWarnings] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function finalize() {
    setBusy(true);
    setError(null);
    try {
      const resp = await fetch(`${API_URL}/author/finalize/${draftId}`, {
        method: "POST",
      });
      if (!resp.ok) {
        throw new Error(`finalize failed: ${resp.status}`);
      }
      const body = (await resp.json()) as { warnings: string[] };
      setWarnings(body.warnings);
      window.location.reload();
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginBottom: 18 }}>
      <button
        onClick={finalize}
        disabled={busy}
        style={{
          background: "var(--ok)",
          color: "#0b0e14",
          fontWeight: 700,
          border: "none",
          borderRadius: 8,
          padding: "8px 18px",
          cursor: "pointer",
        }}
      >
        {busy ? "Finalizing…" : "Finalize & publish"}
      </button>
      {warnings && warnings.length > 0 ? (
        <p className="detail">warnings: {warnings.join("; ")}</p>
      ) : null}
      {error ? <p className="detail">{error}</p> : null}
    </div>
  );
}
