import Link from "next/link";

const LINKS = [
  { href: "/releases", label: "Releases & What Changed" },
  { href: "/roadmap", label: "Roadmap" },
  { href: "/issues", label: "Open Issues" },
  { href: "/activity", label: "Activity" },
];

export default function Nav() {
  return (
    <nav className="topnav">
      <Link href="/" className="brand">
        EUDI Intel
      </Link>
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} className="navlink">
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
