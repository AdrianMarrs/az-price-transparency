import { Building2, MapPin, Stethoscope } from "lucide-react";
import { Link, useSearchParams } from "react-router";

import type { Route } from "./+types/search";
import { serviceResult, SearchBox } from "~/components/search-box";
import { ScoreBadge } from "~/components/score-badge";
import { Card } from "~/components/ui/card";
import { searchServices } from "~/lib/api";
import { searchCities, searchHospitals } from "~/lib/catalog";
import { titleCase } from "~/lib/summary";

export const meta: Route.MetaFunction = () => [
  { title: "Search | Arizona Hospital Prices" },
  { name: "robots", content: "noindex" },
];

export async function clientLoader({ request }: Route.ClientLoaderArgs) {
  const q = new URL(request.url).searchParams.get("q")?.trim() ?? "";
  const services = q.length >= 2 ? await searchServices(q).catch(() => []) : [];
  return { q, services };
}

export default function SearchPage({ loaderData }: Route.ComponentProps) {
  const [params] = useSearchParams();
  const q = params.get("q") ?? loaderData.q;
  const services = loaderData.services.map(serviceResult);
  const hospitals = searchHospitals(q, 50);
  const cities = searchCities(q, 10);
  const total = services.length + hospitals.length + cities.length;

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Search</h1>
      <div className="mt-6"><SearchBox key={q} size="lg" initial={q} /></div>
      {q && (
        <p className="mt-4 text-sm text-muted-foreground" aria-live="polite">
          {total ? `${total} result${total === 1 ? "" : "s"} for “${q}”` : `Nothing matches “${q}”. Try a simpler word, or the billing code.`}
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
      {hospitals.length > 0 && (
        <Section icon={Building2} title="Hospitals">
          {hospitals.map((h) => (
            <li key={h.ccn}>
              <Link to={`/hospitals/${h.ccn}`} className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-muted/50">
                <span>
                  <span className="block font-medium">{titleCase(h.name)}</span>
                  <span className="block text-sm text-muted-foreground">{titleCase(h.city)}</span>
                </span>
                <ScoreBadge score={h.score_pct} />
              </Link>
            </li>
          ))}
        </Section>
      )}
      {cities.length > 0 && (
        <Section icon={MapPin} title="Cities">
          {cities.map((c) => (
            <li key={c.city}>
              <Link to={`/hospitals?city=${encodeURIComponent(c.city)}`} className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-muted/50">
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
