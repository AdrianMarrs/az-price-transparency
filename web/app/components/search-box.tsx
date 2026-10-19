// One search box for the whole site. On a state's pages it finds that state's services (its
// service list), hospitals and cities (its catalog); elsewhere, hospitals anywhere and states
// (services are priced per state). A combobox in the WAI-ARIA sense: arrow keys move through the results,
// Enter opens one (or the full results page), Escape closes the list.

import { Building2, Map as MapIcon, MapPin, Search, Stethoscope } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { searchServices, type Service } from "~/lib/api";
import {
  citiesOf, hospitalIndex, indexEntry, searchCities, searchHospitals, serviceSlug, stateCatalog,
  type City,
} from "~/lib/catalog";
import { searchStates, stateFor, statePath } from "~/lib/states";
import { titleCase } from "~/lib/summary";
import { cn } from "~/lib/utils";

type Result = {
  key: string; href: string; label: string; detail: string; kind: "service" | "hospital" | "city" | "state";
};

const ICONS = { service: Stethoscope, hospital: Building2, city: MapPin, state: MapIcon };
const GROUPS: [Result["kind"], string][] = [
  ["service", "Services"], ["state", "States"], ["hospital", "Hospitals"], ["city", "Cities"],
];

// What the box searches besides services: a state's hospitals and cities, or (with no state)
// every hospital, labeled with its state.
type Places = { hospitals: { ccn: string; name: string; city: string; state: string }[]; cities: City[] };

function usePlaces(state: string | undefined, wanted: boolean): Places {
  const [places, setPlaces] = useState<Places>({ hospitals: [], cities: [] });
  useEffect(() => {
    if (!wanted) return;
    let current = true;
    const load = state
      ? stateCatalog(state).then((c) => ({ hospitals: c.hospitals, cities: citiesOf(c.hospitals) }))
      : hospitalIndex().then((index) => ({ hospitals: index.map(indexEntry), cities: [] }));
    load.then((p) => { if (current) setPlaces(p); }).catch(() => {});
    return () => { current = false; };
  }, [state, wanted]);
  return places;
}

export function serviceResult(state: string, s: Service): Result {
  const code = `${s.code_type === "MS-DRG" ? "DRG" : "CPT"} ${s.code}`;
  return {
    key: s.id,
    kind: "service",
    href: `${statePath(state)}/services/${serviceSlug(s.id)}`,
    label: s.cms_description ?? titleCase(s.description),
    detail: `${code} · ${s.hospitals} hospital${s.hospitals === 1 ? "" : "s"}`,
  };
}

export const searchPage = (q: string, state?: string) =>
  `/search?q=${encodeURIComponent(q)}${state ? `&state=${state.toLowerCase()}` : ""}`;

export function SearchBox({ size = "lg", autoFocus = false, initial = "", state }: {
  size?: "lg" | "sm";
  autoFocus?: boolean;
  initial?: string;
  state?: string; // a state's code: search its services, hospitals and cities
}) {
  const navigate = useNavigate();
  const id = useId();
  const [q, setQ] = useState(initial);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const query = q.trim();
  const places = usePlaces(state, query.length >= 2);
  useEffect(() => {
    if (query.length < 2 || !state) { setServices([]); return; }
    let current = true; // a later keystroke's results win
    setLoading(true);
    const timer = setTimeout(() => {
      searchServices(state, query)
        .then((r) => { if (current) setServices(r.slice(0, 6)); })
        .catch(() => {})
        .finally(() => { if (current) setLoading(false); });
    }, 150);
    return () => { current = false; clearTimeout(timer); };
  }, [query, state]);

  const results = useMemo<Result[]>(() => [
    ...(state ? services.map((s) => serviceResult(state, s)) : []),
    ...(state ? [] : searchStates(query).map((s) => ({
      key: s.code, kind: "state" as const, href: statePath(s),
      label: s.name, detail: `${s.hospitals} hospital${s.hospitals === 1 ? "" : "s"}`,
    }))),
    ...searchHospitals(places.hospitals, query, 5).map((h) => ({
      key: h.ccn, kind: "hospital" as const, href: `/hospitals/${h.ccn}`,
      label: titleCase(h.name), detail: state ? titleCase(h.city) : `${titleCase(h.city)}, ${h.state}`,
    })),
    ...(state ? searchCities(places.cities, query, 3).map((c) => ({
      key: c.city, kind: "city" as const, href: `${statePath(state)}/hospitals?city=${encodeURIComponent(c.city)}`,
      label: titleCase(c.city), detail: `${c.hospitals} hospital${c.hospitals === 1 ? "" : "s"}`,
    })) : []),
  ], [services, places, query, state]);

  useEffect(() => setActive(-1), [results]);

  // Close when focus or a click leaves the box.
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const go = (href: string) => { setOpen(false); setQ(""); navigate(href); };
  const submit = () => {
    if (active >= 0 && results[active]) go(results[active].href);
    else if (query) go(searchPage(query, state));
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, -1)); }
    else if (e.key === "Enter") { e.preventDefault(); submit(); }
    else if (e.key === "Escape") { setOpen(false); setActive(-1); }
  };

  const showList = open && query.length >= 2;
  const lg = size === "lg";

  return (
    <div ref={box} className="relative w-full" role="search">
      <label htmlFor={`${id}-input`} className="sr-only">
        {state ? `Search services, hospitals and cities in ${stateFor(state)?.name ?? state}` : "Search hospitals and states"}
      </label>
      <div className="relative">
        <Search aria-hidden className={cn("pointer-events-none absolute top-1/2 -translate-y-1/2 text-muted-foreground", lg ? "left-4 size-5" : "left-3 size-4")} />
        <input
          id={`${id}-input`}
          type="search"
          role="combobox"
          aria-expanded={showList}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${id}-opt-${active}` : undefined}
          autoComplete="off"
          autoFocus={autoFocus}
          value={q}
          placeholder={state
            ? (lg ? "Try “knee MRI”, “colonoscopy”, a hospital or a city" : "Search services, hospitals, cities")
            : (lg ? "Find a hospital, or your state" : "Search hospitals and states")}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className={cn(
            "w-full rounded-lg border border-input bg-card text-foreground shadow-xs outline-none transition",
            "placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30",
            lg ? "h-14 pl-12 pr-4 text-lg" : "h-9 pl-9 pr-3 text-sm",
          )}
        />
      </div>

      {showList && (
        <div
          id={`${id}-list`}
          role="listbox"
          aria-label="Search results"
          className="absolute z-50 mt-2 max-h-[min(70vh,32rem)] w-full overflow-y-auto rounded-lg border bg-popover p-1.5 text-popover-foreground shadow-lg"
        >
          {results.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              {loading ? "Searching…" : state ? "No matches. Try a simpler word or a billing code."
                : "No hospital or state matches. To compare a service's prices, pick your state first."}
            </p>
          ) : (
            GROUPS.map(([kind, title]) => {
              const items = results.map((r, i) => ({ r, i })).filter(({ r }) => r.kind === kind);
              if (items.length === 0) return null;
              const Icon = ICONS[kind];
              return (
                <div key={kind} role="group" aria-label={title} className="py-1">
                  <p className="px-3 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</p>
                  {items.map(({ r, i }) => (
                    <div
                      key={r.key}
                      id={`${id}-opt-${i}`}
                      role="option"
                      aria-selected={i === active}
                      onMouseEnter={() => setActive(i)}
                      onMouseDown={(e) => { e.preventDefault(); go(r.href); }}
                      className={cn(
                        "flex cursor-pointer items-center gap-3 rounded-md px-3 py-2",
                        i === active && "bg-accent text-accent-foreground",
                      )}
                    >
                      <Icon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate">{r.label}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{r.detail}</span>
                    </div>
                  ))}
                </div>
              );
            })
          )}
          {query && (
            <button
              type="button"
              onMouseDown={(e) => { e.preventDefault(); go(searchPage(query, state)); }}
              className="mt-1 w-full rounded-md border-t px-3 py-2 text-left text-sm text-primary hover:bg-accent"
            >
              See all results for “{query}”
            </button>
          )}
        </div>
      )}
    </div>
  );
}
