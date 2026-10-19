import { FileSearch, Scale, ShieldCheck } from "lucide-react";
import { Link, useNavigate } from "react-router";

import type { Route } from "./+types/home";
import { SearchBox } from "~/components/search-box";
import { NativeSelect } from "~/components/ui/native-select";
import { statePath, states } from "~/lib/states";

const hospitals = states.reduce((n, s) => n + s.hospitals, 0);
const withPrices = states.reduce((n, s) => n + s.withPrices, 0);

export const meta: Route.MetaFunction = () => [
  { title: "Clear Healthcare Prices: compare what hospitals charge, in every state" },
  {
    name: "description",
    content:
      `Published prices at ${hospitals.toLocaleString()} US hospitals: cash prices, list prices and what each insurer pays, with how well each hospital follows the price transparency rules.`,
  },
];

export default function Home() {
  const navigate = useNavigate();
  return (
    <>
      <section data-home-hero className="relative overflow-hidden bg-hero text-hero-foreground">
        <div aria-hidden className="absolute inset-0 bg-[radial-gradient(60rem_30rem_at_80%_-10%,oklch(0.55_0.1_195/0.35),transparent)]" />
        <div className="relative mx-auto max-w-6xl px-4 pb-20 pt-16 sm:px-6 sm:pt-24">
          <p className="text-sm font-medium uppercase tracking-widest text-hero-foreground/70">
            Every state · {hospitals.toLocaleString()} hospitals
          </p>
          <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            See what hospitals charge, before you go.
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-hero-foreground/80 text-pretty">
            Cash prices, list prices and the rates each insurer has agreed to, from the files
            hospitals are required to publish. Prices are compared within a state: pick yours.
          </p>
          <div className="mt-8 grid max-w-2xl gap-3 text-foreground sm:grid-cols-[14rem_1fr]">
            <label className="sr-only" htmlFor="state-picker">Your state</label>
            <NativeSelect
              id="state-picker"
              className="h-14 bg-card text-base"
              defaultValue=""
              onChange={(e) => e.target.value && navigate(statePath(e.target.value))}
            >
              <option value="" disabled>Choose your state</option>
              {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </NativeSelect>
            <SearchBox size="lg" />
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-6">
        <dl className="relative z-10 -mt-8 grid gap-px overflow-hidden rounded-xl border bg-border shadow-sm sm:grid-cols-3">
          {[
            [hospitals.toLocaleString(), "Hospitals covered", "Every non-federal hospital in 50 states, DC and Puerto Rico"],
            [withPrices.toLocaleString(), "Publish prices we can read", "From their machine-readable price files"],
            [states.length.toString(), "States and territories", "Each with its own prices, services and scores"],
          ].map(([value, label, note]) => (
            <div key={label} className="bg-card px-6 py-5">
              <dt className="text-sm text-muted-foreground">{label}</dt>
              <dd className="mt-1 text-3xl font-semibold tracking-tight tabular">{value}</dd>
              <dd className="mt-1 text-xs text-muted-foreground">{note}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section id="states" className="mx-auto mt-20 max-w-6xl scroll-mt-24 px-4 sm:px-6" aria-labelledby="states-heading">
        <h2 id="states-heading" className="text-2xl font-semibold tracking-tight">Pick a state</h2>
        <p className="mt-1 text-muted-foreground">
          How many of each state's hospitals publish a price file we can read.
        </p>
        <ul className="mt-6 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {states.map((s) => (
            <li key={s.code}>
              <Link to={statePath(s)} className="flex items-baseline justify-between gap-3 rounded-lg border bg-card px-4 py-3 hover:border-primary hover:text-primary">
                <span className="font-medium">{s.name}</span>
                <span className="shrink-0 text-sm tabular text-muted-foreground">
                  {s.withPrices} of {s.hospitals}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="mx-auto mt-20 max-w-6xl px-4 sm:px-6" aria-labelledby="how-heading">
        <h2 id="how-heading" className="text-2xl font-semibold tracking-tight">How it works</h2>
        <div className="mt-6 grid gap-6 sm:grid-cols-3">
          {[
            [FileSearch, "Read the files", "We find each hospital's price file through the cms-hpt.txt file the federal rule requires on its website, and read it in CMS's format."],
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
        <p className="mt-8 text-sm text-muted-foreground">
          <Link to="/methods" className="text-primary hover:underline">How it works, and its limits</Link>
        </p>
      </section>
    </>
  );
}
