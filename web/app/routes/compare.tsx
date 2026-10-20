// Two states side by side for one service: the average of each state's hospital prices.
// The page is a static shell (pre-rendered with its defaults); the browser loads both
// states' price files for the chosen service and works out the numbers.

import { ArrowLeftRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import type { Route } from "./+types/compare";
import { AdSlot } from "~/components/ad-slot";
import { Card } from "~/components/ui/card";
import { NativeSelect } from "~/components/ui/native-select";
import { Skeleton } from "~/components/ui/skeleton";
import { comparePrices, NotFound } from "~/lib/api";
import { categories, featuredServices } from "~/lib/catalog";
import { stateFor, statePath, states, type StateSummary } from "~/lib/states";
import { money, moneyRange, stateStats, type Filters, type StateStats } from "~/lib/summary";
import { useHydrated } from "~/lib/utils";

export const meta: Route.MetaFunction = () => [
  { title: "Compare hospital prices between two states | Clear Healthcare Prices" },
  {
    name: "description",
    content: "Pick a procedure and two states to compare the average price their hospitals publish: what insurers pay and the cash price.",
  },
];

const DEFAULTS = { service: "cpt-73721", a: "az", b: "ca", market: "" };

// The markets worth comparing on their own; "" is every market together.
const MARKET_CHOICES: [string, string][] = [
  ["", "Every insurance market"],
  ["commercial", "Commercial (job-based and private)"],
  ["medicare_advantage", "Medicare Advantage"],
  ["medicaid", "Medicaid"],
  ["exchange", "Marketplace"],
];

type Side = { state: StateSummary; stats: StateStats | null } | "loading" | "error";

function useStateStats(code: string, service: string, market: string): Side {
  const [side, setSide] = useState<Side>("loading");
  useEffect(() => {
    const state = stateFor(code);
    if (!state) return setSide("error");
    const controller = new AbortController();
    setSide("loading");
    const filters: Filters = { county: "", setting: "any", market, payer: "" };
    comparePrices(state.code, service, controller.signal).then(
      (c) => setSide({ state, stats: stateStats(c.hospitals, filters) }),
      (e) => {
        if (controller.signal.aborted) return;
        // No file: no hospital in the state lists the service.
        setSide(e instanceof NotFound ? { state, stats: null } : "error");
      },
    );
    return () => controller.abort();
  }, [code, service, market]);
  return side;
}

export default function ComparePage() {
  const [urlParams, setParams] = useSearchParams();
  // Pre-rendered with the defaults; the URL's choices apply once the page has hydrated.
  const hydrated = useHydrated();
  const pick = (key: keyof typeof DEFAULTS) => (hydrated && urlParams.get(key)) || DEFAULTS[key];
  const service = featuredServices.find((s) => s.slug === pick("service")) ?? featuredServices.find((s) => s.slug === DEFAULTS.service)!;
  const a = stateFor(pick("a"))?.code.toLowerCase() ?? DEFAULTS.a;
  const b = stateFor(pick("b"))?.code.toLowerCase() ?? DEFAULTS.b;
  const market = pick("market");

  const set = (patch: Partial<typeof DEFAULTS>) => {
    const next = { service: service.slug, a, b, market, ...patch };
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(next)) if (v) params.set(k, v);
    setParams(params, { replace: true, preventScrollReset: true });
  };

  const left = useStateStats(a, service.slug, market);
  const right = useStateStats(b, service.slug, market);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight text-balance">Compare two states</h1>
      <p className="mt-2 max-w-2xl text-muted-foreground text-pretty">
        The average price hospitals in each state publish for one procedure. Pick a service and
        two states.
      </p>

      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.6fr_1fr_auto_1fr_1.2fr] lg:items-end">
        <Field label="Service" className="sm:col-span-2 lg:col-span-1">
          <NativeSelect value={service.slug} onChange={(e) => set({ service: e.target.value })}>
            {categories.map((category) => (
              <optgroup key={category} label={category}>
                {featuredServices.filter((s) => s.category === category).map((s) => (
                  <option key={s.slug} value={s.slug}>{s.description}</option>
                ))}
              </optgroup>
            ))}
          </NativeSelect>
        </Field>
        <Field label="First state">
          <StatePicker value={a} onChange={(v) => set({ a: v })} />
        </Field>
        <button
          type="button"
          onClick={() => set({ a: b, b: a })}
          className="hidden size-9 items-center justify-center rounded-md border bg-card text-muted-foreground hover:border-primary hover:text-primary lg:flex"
          title="Swap the states"
        >
          <ArrowLeftRight aria-hidden className="size-4" />
          <span className="sr-only">Swap the states</span>
        </button>
        <Field label="Second state">
          <StatePicker value={b} onChange={(v) => set({ b: v })} />
        </Field>
        <Field label="Insurance" className="sm:col-span-2 lg:col-span-1">
          <NativeSelect value={market} onChange={(e) => set({ market: e.target.value })}>
            {MARKET_CHOICES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </NativeSelect>
        </Field>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <StateCard side={left} slug={service.slug} />
        <StateCard side={right} slug={service.slug} />
      </div>

      <Difference left={left} right={right} />
      <AdSlot className="mt-10 px-0 sm:px-0" />

      <div className="mt-10 max-w-3xl space-y-2 text-sm text-muted-foreground">
        <p>
          <span className="font-medium text-foreground">How the average is worked out.</span>{" "}
          For each hospital we take the median of the prices it lists for the service with each
          insurer plan (left out: $1 stand-ins and prices given as a percentage). The state's
          average is the mean of those hospital medians, so every hospital counts once, however
          many plans it lists. It isn't weighted by how often each hospital does the procedure;
          the price files don't say.
        </p>
        <p>
          The cash price is each hospital's lowest listed self-pay price. States differ in how
          many hospitals publish files we can read, so a state with few hospitals here is a
          thin sample. <Link to="/methods" className="text-primary hover:underline">More on the method and its limits</Link>.
        </p>
      </div>
    </div>
  );
}

function Field({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={className}>
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

function StatePicker({ value, onChange }: { value: string; onChange: (code: string) => void }) {
  return (
    <NativeSelect value={value.toUpperCase()} onChange={(e) => onChange(e.target.value.toLowerCase())}>
      {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
    </NativeSelect>
  );
}

function StateCard({ side, slug }: { side: Side; slug: string }) {
  if (side === "loading") {
    return (
      <Card className="px-6" aria-busy="true">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-12 w-1/2" />
        <Skeleton className="h-16 w-full" />
      </Card>
    );
  }
  if (side === "error") {
    return <Card className="px-6 text-muted-foreground">This state's prices didn't load. Please try again in a moment.</Card>;
  }
  const { state, stats } = side;
  const link = `${statePath(state)}/services/${slug}`;
  return (
    <Card className="gap-4 px-6">
      <h2 className="text-lg font-semibold">{state.name}</h2>
      {!stats || stats.hospitals === 0 ? (
        <p className="text-muted-foreground">
          {stats && stats.cashHospitals > 0
            ? `No ${state.name} hospital lists an insurer dollar price for this, for this market.`
            : `No ${state.name} hospital we can read lists a price for this service.`}
          {stats && stats.cashAverage != null && <> Average cash price: <span className="font-medium text-foreground tabular">{money(stats.cashAverage)}</span>.</>}
        </p>
      ) : (
        <>
          <div>
            <p className="text-sm text-muted-foreground">Average insurer price</p>
            <p className="text-4xl font-semibold tracking-tight tabular">{money(stats.average)}</p>
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <Stat label="Median hospital" value={money(stats.median)} />
            <Stat label="Average cash price" value={money(stats.cashAverage)} note={stats.cashHospitals ? `${stats.cashHospitals} hospital${stats.cashHospitals === 1 ? "" : "s"}` : undefined} />
            <Stat label="Lowest to highest hospital" value={moneyRange(stats.range)} />
            <Stat label="Hospitals with insurer prices" value={stats.hospitals.toLocaleString()} note={`of ${state.withPrices} with readable files`} />
          </dl>
          <Link to={link} className="text-sm text-primary hover:underline">Every {state.name} hospital's price</Link>
        </>
      )}
    </Card>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular">{value}</dd>
      {note && <dd className="text-xs text-muted-foreground">{note}</dd>}
    </div>
  );
}

function Difference({ left, right }: { left: Side; right: Side }) {
  if (typeof left === "string" || typeof right === "string") return null;
  const x = left.stats?.average;
  const y = right.stats?.average;
  if (x == null || y == null || left.state.code === right.state.code) return null;
  const [cheap, dear, low, high] = x <= y ? [left.state, right.state, x, y] : [right.state, left.state, y, x];
  const pct = Math.round((1 - low / high) * 100);
  return (
    <p className="mt-6 rounded-lg border bg-muted/40 px-5 py-4 text-pretty">
      {pct === 0 ? (
        <>The two averages are within 1% of each other.</>
      ) : (
        <>
          On average, {cheap.name} hospitals list insurer prices{" "}
          <span className="font-semibold">{pct}% lower</span> than {dear.name} hospitals:{" "}
          <span className="tabular">{money(low)}</span> against <span className="tabular">{money(high)}</span>,{" "}
          a difference of <span className="font-semibold tabular">{money(high - low)}</span>.
        </>
      )}
    </p>
  );
}
