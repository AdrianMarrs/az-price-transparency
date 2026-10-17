// The header and footer on every page.

import { NavLink, Link } from "react-router";

import { SearchBox } from "~/components/search-box";
import { cn } from "~/lib/utils";

export function Logo({ className }: { className?: string }) {
  // A price tag over a cross: prices for care.
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={className}>
      <rect width="32" height="32" rx="8" className="fill-primary" />
      <path d="M13 8h6v5h5v6h-5v5h-6v-5H8v-6h5z" className="fill-primary-foreground" />
    </svg>
  );
}

const NAV = [
  { to: "/services", label: "Services" },
  { to: "/hospitals", label: "Hospitals" },
  { to: "/methods", label: "How it works" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Link to="/" className="flex shrink-0 items-center gap-2.5 font-semibold tracking-tight">
          <Logo className="size-8" />
          <span className="hidden sm:inline">Arizona Hospital Prices</span>
          <span className="sm:hidden">AZ Prices</span>
        </Link>
        <nav aria-label="Main" className="ml-2 hidden items-center gap-1 md:flex">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) => cn(
                "rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground",
                isActive && "text-foreground font-medium",
              )}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        {/* Hidden by CSS, not by route, on the home page (it has its own big search box): the
            app shell for pages that aren't pre-rendered is rendered at "/", and the first
            render in the browser must match it. */}
        <div className="ml-auto w-full max-w-sm in-[body:has([data-home-hero])]:hidden">
          <SearchBox size="sm" />
        </div>
      </div>
      <nav aria-label="Main" className="flex gap-1 overflow-x-auto border-t px-2 md:hidden">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            className={({ isActive }) => cn("px-3 py-2 text-sm text-muted-foreground", isActive && "text-foreground font-medium")}
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t bg-muted/40">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 text-sm text-muted-foreground sm:grid-cols-3 sm:px-6">
        <div className="space-y-2 sm:col-span-2">
          <p className="font-medium text-foreground">These are published prices, not quotes.</p>
          <p>
            What you pay depends on your plan, deductible and the care you actually get. Ask your
            insurer and the hospital for an estimate before you book.
          </p>
          <p>
            Hospital prices come from each hospital's machine-readable price file, checked weekly;
            insurer rates from insurers' Transparency in Coverage files, monthly.
          </p>
        </div>
        <div className="space-y-2">
          <p className="font-medium text-foreground">About</p>
          <ul className="space-y-1.5">
            <li><Link className="hover:text-foreground" to="/methods">How it works and its limits</Link></li>
            <li><a className="hover:text-foreground" href="https://github.com/AdrianMarrs/az-price-transparency">Source code on GitHub</a></li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
