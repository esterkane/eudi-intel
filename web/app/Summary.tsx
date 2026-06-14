import type { EntitySummary } from "../lib/api";

// Structured S2 summary block: tells you exactly what the entity is about.
export default function SummaryBlock({ summary }: { summary: EntitySummary | null }) {
  if (!summary) return null;
  const insufficient = summary.tl_dr === "insufficient detail to summarize";
  return (
    <div className={`summary ${insufficient ? "summary-thin" : ""}`}>
      <p className="summary-tldr">{summary.tl_dr}</p>
      {!insufficient ? (
        <>
          <div className="summary-tags">
            <span className="badge category">{summary.category.replace("_", " ")}</span>
            {summary.components.slice(0, 4).map((c) => (
              <span key={c} className="chip">
                {c}
              </span>
            ))}
          </div>
          {summary.recommended_action ? (
            <p className="summary-action">
              <strong>Action:</strong> {summary.recommended_action}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
