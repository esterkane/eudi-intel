import Link from "next/link";

const LINKS = [
  { href: "/support", label: "Support" },
  { href: "/search", label: "Search" },
  { href: "/releases", label: "Releases & What Changed" },
  { href: "/roadmap", label: "Roadmap" },
  { href: "/issues", label: "Open Issues" },
  { href: "/activity", label: "Activity" },
  { href: "/drafts", label: "Drafts" },
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
