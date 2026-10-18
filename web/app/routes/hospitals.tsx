import { Link, useSearchParams } from "react-router";

import type { Route } from "./+types/hospitals";
import { ScoreBadge } from "~/components/score-badge";
import { Card } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { NativeSelect } from "~/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "~/components/ui/table";
import { cities, hospitals, matches } from "~/lib/catalog";
import { titleCase } from "~/lib/summary";

export const meta: Route.MetaFunction = () => [
  { title: "Arizona hospitals and their price transparency scores | Clear Healthcare Prices" },
  { name: "description", content: `All ${hospitals.length} non-federal Arizona hospitals: where each is, what kind of hospital it is, and how well it follows the federal price transparency rules.` },
];

const TYPES = [...new Set(hospitals.map((h) => h.hospital_type))].sort();
const ALL = "all";
type Sort = "name" | "score" | "services";

export default function Hospitals() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const city = params.get("city") ?? ALL;
  const type = params.get("type") ?? ALL;
  const sort = (params.get("sort") as Sort) ?? "name";

  const set = (key: string, value: string, empty = "") => {
    const next = new URLSearchParams(params);
    if (value === empty || value === ALL) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true, preventScrollReset: true });
  };

  const rows = hospitals
    .filter((h) => (city === ALL || h.city === city) && (type === ALL || h.hospital_type === type))
    .filter((h) => !q || matches(q, `${h.name} ${h.city} ${h.county}`))
    .sort((a, b) =>
      sort === "score" ? (b.score_pct ?? -1) - (a.score_pct ?? -1) || a.name.localeCompare(b.name)
      : sort === "services" ? b.services - a.services
      : a.name.localeCompare(b.name));

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Hospitals</h1>
      <p className="mt-2 max-w-2xl text-muted-foreground">
        Every non-federal Arizona hospital, scored on the federal price transparency rules we can
        check. VA and Indian Health Service hospitals aren't required to publish prices.
      </p>

      <div className="mt-8 grid gap-3 sm:grid-cols-[1fr_auto_auto_auto]">
        <label className="sr-only" htmlFor="hospital-filter">Filter hospitals</label>
        <Input id="hospital-filter" type="search" placeholder="Filter by name or city" value={q} onChange={(e) => set("q", e.target.value)} />
        <NativeSelect className="sm:w-48" aria-label="City" value={city} onChange={(e) => set("city", e.target.value)}>
          <option value={ALL}>All cities</option>
          {[...cities].sort((a, b) => a.city.localeCompare(b.city)).map((c) => (
            <option key={c.city} value={c.city}>{titleCase(c.city)} ({c.hospitals})</option>
          ))}
        </NativeSelect>
        <NativeSelect className="sm:w-56" aria-label="Hospital type" value={type} onChange={(e) => set("type", e.target.value)}>
          <option value={ALL}>All types</option>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </NativeSelect>
        <NativeSelect className="sm:w-52" aria-label="Sort by" value={sort} onChange={(e) => set("sort", e.target.value, "name")}>
          <option value="name">Sort: Name</option>
          <option value="score">Sort: Transparency score</option>
          <option value="services">Sort: Services priced</option>
        </NativeSelect>
      </div>

      <p className="mt-4 text-sm text-muted-foreground" aria-live="polite">
        {rows.length} of {hospitals.length} hospitals
      </p>

      <Card className="mt-3 py-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-5">Hospital</TableHead>
              <TableHead className="hidden md:table-cell">Type</TableHead>
              <TableHead className="text-right">Services priced</TableHead>
              <TableHead className="pr-5">Transparency</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((h) => (
              <TableRow key={h.ccn}>
                <TableCell className="whitespace-normal pl-5">
                  <Link to={`/hospitals/${h.ccn}`} className="font-medium hover:text-primary hover:underline">
                    {titleCase(h.name)}
                  </Link>
                  <span className="block text-sm text-muted-foreground">{titleCase(h.city)}</span>
                </TableCell>
                <TableCell className="hidden text-muted-foreground md:table-cell">{h.hospital_type}</TableCell>
                <TableCell className="text-right tabular">{h.services ? h.services.toLocaleString() : "—"}</TableCell>
                <TableCell className="pr-5"><ScoreBadge score={h.score_pct} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
