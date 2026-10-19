import { ArrowRight, FileSearch, Scale, ShieldCheck } from "lucide-react";
import { Link } from "react-router";

import type { Route } from "./+types/state";
import { ScoreBadge } from "~/components/score-badge";
import { SearchBox } from "~/components/search-box";
import { Card, CardContent } from "~/components/ui/card";
import { categories, featuredServices } from "~/lib/catalog";
import { stateData } from "~/lib/state-page";
import { statePath } from "~/lib/states";
import { titleCase } from "~/lib/summary";

// At build time (pre-rendering); in the browser for a state that wasn't pre-rendered.
export const loader = ({ params }: Route.LoaderArgs) => stateData(params.state);
export const clientLoader = ({ params }: Route.ClientLoaderArgs) => stateData(params.state);

export const meta: Route.MetaFunction = ({ loaderData }) => {
  if (!loaderData) return [{ title: "Not found | Clear Healthcare Prices" }];
  const name = loaderData.state.name;
  return [
    { title: `Clear Healthcare Prices: compare what ${name} hospitals charge` },
    {
      name: "description",
      content: `Search published prices at every ${name} hospital: cash prices, list prices and what each insurer pays, with how well each hospital follows the price transparency rules.`,
    },
  ];
};

// Short names for the chips; CMS's own descriptions are long ("Diagnostic examination of
// large bowel using an endoscope").
const POPULAR: [string, string][] = [
  ["cpt-73721", "Knee MRI"], ["cpt-45378", "Colonoscopy"], ["cpt-70450", "Head CT"],
  ["cpt-59400", "Childbirth"], ["cpt-99203", "New patient visit"], ["drg-470", "Hip or knee replacement"],
];

export default function StateHome({ loaderData: { state, catalog } }: Route.ComponentProps) {
  const { hospitals } = catalog;
  const st = statePath(state);
  const priced = new Set(catalog.featured);
  const popular = POPULAR.filter(([slug]) => priced.has(slug));
  const scored = hospitals.filter((h) => h.score_pct != null);
  const meetsAll = scored.filter((h) => h.score_pct === 100).length;
  const withPrices = hospitals.filter((h) => h.services > 0).length;
  const leaders = [...scored].sort((a, b) => (b.score_pct ?? 0) - (a.score_pct ?? 0) || b.services - a.services).slice(0, 5);

  return (
    <>
      <section data-home-hero className="relative overflow-hidden bg-hero text-hero-foreground">
        <div aria-hidden className="absolute inset-0 bg-[radial-gradient(60rem_30rem_at_80%_-10%,oklch(0.55_0.1_195/0.35),transparent)]" />
        <div className="relative mx-auto max-w-6xl px-4 pb-20 pt-16 sm:px-6 sm:pt-24">
          <p className="text-sm font-medium uppercase tracking-widest text-hero-foreground/70">
            <Link to="/" className="hover:text-hero-foreground">All states</Link> · {state.name} · {hospitals.length} hospitals
          </p>
          <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            See what {state.name} hospitals charge, before you go.
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-hero-foreground/80 text-pretty">
            Cash prices, list prices and the rates each insurer has agreed to, from the files
            hospitals and insurers are required to publish.
          </p>
          <div className="mt-8 max-w-2xl text-foreground">
            <SearchBox size="lg" state={state.code} />
          </div>
          {popular.length > 0 && <div className="mt-5 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-hero-foreground/70">Popular:</span>
            {popular.map(([slug, label]) => (
              <Link
                key={slug}
                to={`${st}/services/${slug}`}
                className="rounded-full bg-white/10 px-3 py-1 text-hero-foreground ring-1 ring-white/15 transition hover:bg-white/20"
              >
                {label}
              </Link>
            ))}
          </div>}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-6">
        <dl className="relative z-10 -mt-8 grid gap-px overflow-hidden rounded-xl border bg-border shadow-sm sm:grid-cols-3">
          {[
            [hospitals.length.toString(), `${state.name} hospitals covered`, "Every non-federal hospital in the state"],
            [withPrices.toString(), "Publish prices we can read", "From their machine-readable price files"],
            [`${meetsAll} of ${scored.length}`, "Are 100% transparent", "Meet every federal rule we can check"],
          ].map(([value, label, note]) => (
            <div key={label} className="bg-card px-6 py-5">
              <dt className="text-sm text-muted-foreground">{label}</dt>
              <dd className="mt-1 text-3xl font-semibold tracking-tight tabular">{value}</dd>
              <dd className="mt-1 text-xs text-muted-foreground">{note}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="mx-auto mt-20 max-w-6xl px-4 sm:px-6" aria-labelledby="services-heading">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 id="services-heading" className="text-2xl font-semibold tracking-tight">Common services</h2>
            <p className="mt-1 text-muted-foreground">
              The {featuredServices.length} services CMS says patients can shop for, by category.
            </p>
          </div>
          <Link to={`${st}/services`} className="hidden shrink-0 items-center gap-1 text-sm font-medium text-primary hover:underline sm:inline-flex">
            All services <ArrowRight className="size-4" />
          </Link>
        </div>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map((category) => {
            const items = featuredServices.filter((s) => s.category === category);
            return (
              <Card key={category} className="gap-3 py-5">
                <CardContent className="px-5">
                  <h3 className="font-medium">{category}</h3>
                  <ul className="mt-3 space-y-1.5 text-sm">
                    {items.slice(0, 5).map((s) => (
                      <li key={s.slug}>
                        <Link to={`${st}/services/${s.slug}`} title={s.description} className={priced.has(s.slug) ? "line-clamp-2 text-muted-foreground hover:text-primary" : "line-clamp-2 text-muted-foreground/60 hover:text-primary"}>
                          {s.description}
                        </Link>
                      </li>
                    ))}
                  </ul>
                  {items.length > 5 && (
                    <Link to={`${st}/services#${encodeURIComponent(category)}`} className="mt-3 inline-block text-sm text-primary hover:underline">
                      {items.length - 5} more
                    </Link>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      <section className="mx-auto mt-20 grid max-w-6xl grid-cols-1 gap-10 px-4 sm:px-6 lg:grid-cols-5" aria-labelledby="transparency-heading">
        <div className="lg:col-span-2">
          <h2 id="transparency-heading" className="text-2xl font-semibold tracking-tight">Who follows the rules</h2>
          <p className="mt-2 text-muted-foreground text-pretty">
            Since 2021, hospitals must publish their prices in a file anyone can download. We check
            each hospital against the rules a program can verify: that the file exists, is current,
            follows CMS's format and includes the shoppable services.
          </p>
          <Link to={`${st}/hospitals`} className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
            See every hospital's score <ArrowRight className="size-4" />
          </Link>
        </div>
        <Card className="py-2 lg:col-span-3">
          <ul className="divide-y">
            {leaders.map((h) => (
              <li key={h.ccn}>
                <Link to={`/hospitals/${h.ccn}`} className="flex items-center gap-4 px-5 py-3 hover:bg-muted/50">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{titleCase(h.name)}</span>
                    <span className="block text-sm text-muted-foreground">{titleCase(h.city)}</span>
                  </span>
                  <ScoreBadge score={h.score_pct} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </section>

      <section className="mx-auto mt-20 max-w-6xl px-4 sm:px-6" aria-labelledby="how-heading">
        <h2 id="how-heading" className="text-2xl font-semibold tracking-tight">How it works</h2>
        <div className="mt-6 grid gap-6 sm:grid-cols-3">
          {[
            [FileSearch, "Read the files", `We download every ${state.name} hospital's price file we can find and read it in CMS's format: millions of prices, matched by billing code.`],
            [Scale, "Compare like with like", "Prices are matched by billing code, setting and type of charge, so a facility fee is never compared with a doctor's fee."],
            [ShieldCheck, "Show the limits", "These are published prices, not quotes. Each page says where its numbers come from and what they can't tell you."],
          ].map(([Icon, title, text]) => {
            const I = Icon as typeof FileSearch;
            return (
              <div key={title as string}>
                <I aria-hidden className="size-6 text-primary" />
                <h3 className="mt-3 font-medium">{title as string}</h3>
                <p className="mt-1 text-sm text-muted-foreground text-pretty">{text as string}</p>
              </div>
            );
          })}
        </div>
      </section>
    </>
  );
}
