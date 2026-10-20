// The header and footer on every page.

import { ChevronDown } from "lucide-react";
import { useId } from "react";
import { NavLink, Link, useLocation, useNavigate } from "react-router";

import { SearchBox } from "~/components/search-box";
import { featuredServices, stateCatalog } from "~/lib/catalog";
import { statePath, states, type StateSummary } from "~/lib/states";
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

// A state's pages when the page is about one; otherwise the state picker.
function nav(state?: StateSummary) {
  const methods = { to: "/methods", label: "How it works" };
  const compare = { to: state ? `/compare?a=${state.code.toLowerCase()}` : "/compare", label: "Compare" };
  if (!state) return [{ to: "/", label: "States" }, compare, methods];
  const st = statePath(state);
  return [
    { to: `${st}/services`, label: "Services" },
    { to: `${st}/hospitals`, label: "Hospitals" },
    compare,
    methods,
  ];
}

const featuredSlugs = new Set(featuredServices.map((s) => s.slug));

// The same page in another state: /tx/services/x -> /ca/services/x when California prices
// x, else California's services; a hospital's page -> the state's home. A city filter
// (?city=) belongs to one state, so the query string is dropped.
async function samePageIn(pathname: string, to: StateSummary): Promise<string> {
  const st = statePath(to);
  const [, , section, slug] = pathname.split("/");
  if (pathname.startsWith("/hospitals/") || !section) return st;
  if (section === "services" && slug && featuredSlugs.has(slug)) {
    const priced = await stateCatalog(to.code).then((c) => c.featured.includes(slug), () => true);
    return priced ? `${st}/services/${slug}` : `${st}/services`;
  }
  return slug ? `${st}/${section}/${slug}` : `${st}/${section}`;
}

// The state chip next to the site's name: a select, so changing state is one tap.
function StateSwitcher({ state, className }: { state: StateSummary; className?: string }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const id = useId(); // the header has two: one for wide screens, one for phones
  return (
    <div className={cn("relative shrink-0", className)}>
      <label htmlFor={id} className="sr-only">State</label>
      <select
        id={id}
        value={state.code}
        title="Change state"
        onChange={async (e) => {
          const to = states.find((s) => s.code === e.target.value);
          if (to) navigate(await samePageIn(pathname, to));
        }}
        className={cn(
          "field-sizing-content h-7 cursor-pointer appearance-none rounded-full border bg-card pl-3 pr-7 text-xs font-medium text-muted-foreground outline-none transition-colors",
          "hover:border-primary hover:text-primary focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30",
        )}
      >
        {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
      </select>
      <ChevronDown aria-hidden className="pointer-events-none absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}

export function SiteHeader({ state }: { state?: StateSummary }) {
  const NAV = nav(state);
  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Link to="/" className="flex shrink-0 items-center gap-2.5 font-semibold tracking-tight">
          <Logo className="size-8" />
          <span className="text-sm leading-tight sm:text-base">Clear Healthcare Prices</span>
        </Link>
        {state && <StateSwitcher key={state.code} state={state} className="hidden sm:block" />}
        <nav aria-label="Main" className="ml-2 hidden items-center gap-1 md:flex">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) => cn(
                "whitespace-nowrap rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground",
                isActive && "text-foreground font-medium",
              )}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        {/* Hidden by CSS, not by route, on the home pages (the country's and each state's),
            which have their own big search box: the app shell for pages that aren't
            pre-rendered is rendered at "/", and the first render in the browser must match it. */}
        <div className="ml-auto w-full max-w-sm in-[body:has([data-home-hero])]:hidden">
          <SearchBox size="sm" state={state?.code} />
        </div>
      </div>
      <nav aria-label="Main" className="flex items-center gap-1 overflow-x-auto border-t px-2 md:hidden">
        {state && <StateSwitcher key={state.code} state={state} className="ml-1 mr-1 sm:hidden" />}
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === "/"}
            className={({ isActive }) => cn("whitespace-nowrap px-3 py-2 text-sm text-muted-foreground", isActive && "text-foreground font-medium")}
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
            Hospital prices come from each hospital's machine-readable price file, as downloaded
            in October 2026.
          </p>
        </div>
        <div className="space-y-2">
          <p className="font-medium text-foreground">About</p>
          <ul className="space-y-1.5">
            <li><Link className="hover:text-foreground" to="/methods">How it works and its limits</Link></li>
            <li><Link className="hover:text-foreground" to="/privacy">Privacy and ads</Link></li>
            <li><Link className="hover:text-foreground" to="/support">Support the site</Link></li>
            <li><a className="hover:text-foreground" href="https://github.com/AdrianMarrs/az-price-transparency">Source code on GitHub</a></li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
