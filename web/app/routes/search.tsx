import { Building2, Map as MapIcon, MapPin, Stethoscope } from "lucide-react";
import { Link, useSearchParams } from "react-router";

import type { Route } from "./+types/search";
import { serviceResult, SearchBox } from "~/components/search-box";
import { ScoreBadge } from "~/components/score-badge";
import { Card } from "~/components/ui/card";
import { searchServices } from "~/lib/api";
import {
  citiesOf, hospitalIndex, indexEntry, searchCities, searchHospitals, stateCatalog, type City,
} from "~/lib/catalog";
import { searchStates, stateFor, statePath, type StateSummary } from "~/lib/states";
import { titleCase } from "~/lib/summary";

export const meta: Route.MetaFunction = () => [
  { title: "Search | Clear Healthcare Prices" },
  { name: "robots", content: "noindex" },
];

// ?state=tx searches one state's services, hospitals and cities; without it, hospitals
// anywhere and states.
export async function clientLoader({ request }: Route.ClientLoaderArgs) {
  const url = new URL(request.url);
  const q = url.searchParams.get("q")?.trim() ?? "";
  const state = stateFor(url.searchParams.get("state") ?? undefined);
  const wanted = q.length >= 2;
  const [services, hospitals, cities] = await Promise.all([
    state && wanted ? searchServices(state.code, q).catch(() => []) : [],
    !wanted ? [] : state
      ? stateCatalog(state.code).then((c) => c.hospitals).catch(() => [])
      : hospitalIndex().then((index) => index.map(indexEntry)).catch(() => []),
    state && wanted ? stateCatalog(state.code).then((c) => citiesOf(c.hospitals)).catch((): City[] => []) : [],
  ]);
  return { q, state, services, hospitals: searchHospitals(hospitals, q, 50), cities: searchCities(cities, q, 10) };
}

export default function SearchPage({ loaderData }: Route.ComponentProps) {
  const [params] = useSearchParams();
  const q = params.get("q") ?? loaderData.q;
  const { state, hospitals, cities } = loaderData;
  const services = state ? loaderData.services.map((s) => serviceResult(state.code, s)) : [];
  const places: StateSummary[] = state ? [] : searchStates(q, 10);
  const total = services.length + places.length + hospitals.length + cities.length;

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">{state ? `Search ${state.name}` : "Search"}</h1>
      <div className="mt-6"><SearchBox key={q} size="lg" initial={q} state={state?.code} /></div>
      {q && (
        <p className="mt-4 text-sm text-muted-foreground" aria-live="polite">
          {total ? `${total} result${total === 1 ? "" : "s"} for “${q}”`
            : state ? `Nothing matches “${q}”. Try a simpler word, or the billing code.`
            : `No hospital or state matches “${q}”. To compare a service's prices, pick your state first.`}
        </p>
      )}

      {services.length > 0 && (
        <Section icon={Stethoscope} title="Services">
          {services.map((s) => (
            <li key={s.key}>
              <Link to={s.href} className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-muted/50">
                <span>{s.label}</span>
                <span className="shrink-0 text-sm text-muted-foreground">{s.detail}</span>
              </Link>
            </li>
          ))}
        </Section>
      )}
      {places.length > 0 && (
        <Section icon={MapIcon} title="States">
          {places.map((s) => (
            <li key={s.code}>
              <Link to={statePath(s)} className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-muted/50">
                <span>{s.name}</span>
                <span className="text-sm text-muted-foreground">{s.hospitals} hospital{s.hospitals === 1 ? "" : "s"}</span>
              </Link>
            </li>
          ))}
        </Section>
      )}
      {hospitals.length > 0 && (
        <Section icon={Building2} title="Hospitals">
          {hospitals.map((h) => (
            <li key={h.ccn}>
              <Link to={`/hospitals/${h.ccn}`} className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-muted/50">
                <span>
                  <span className="block font-medium">{titleCase(h.name)}</span>
                  <span className="block text-sm text-muted-foreground">{titleCase(h.city)}{state ? "" : `, ${h.state}`}</span>
                </span>
                {"score_pct" in h && <ScoreBadge score={h.score_pct as number | null} />}
              </Link>
            </li>
          ))}
        </Section>
      )}
      {cities.length > 0 && (
        <Section icon={MapPin} title="Cities">
          {cities.map((c) => (
            <li key={c.city}>
              <Link to={`${statePath(state!)}/hospitals?city=${encodeURIComponent(c.city)}`} className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-muted/50">
                <span>{titleCase(c.city)}</span>
                <span className="text-sm text-muted-foreground">{c.hospitals} hospital{c.hospitals === 1 ? "" : "s"}</span>
              </Link>
            </li>
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({ icon: Icon, title, children }: { icon: typeof MapPin; title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8" aria-label={title}>
      <h2 className="flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        <Icon aria-hidden className="size-4" /> {title}
      </h2>
      <Card className="mt-3 py-1"><ul className="divide-y">{children}</ul></Card>
    </section>
  );
}
