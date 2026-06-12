import HealthStatus from "./HealthStatus";

export default function Home() {
  return (
    <main>
      <h1>EUDI Intelligence &amp; Authoring Workbench</h1>
      <p className="subtitle">
        Phase 0 scaffold — local, citation-first intelligence for the EU Digital
        Identity ecosystem.
      </p>
      <HealthStatus />
    </main>
  );
}
