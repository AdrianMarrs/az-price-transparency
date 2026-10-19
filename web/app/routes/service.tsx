import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, Info } from "lucide-react";
import { Fragment, useState } from "react";
import { data, Link, useSearchParams } from "react-router";

import type { Route } from "./+types/service";
import { ScoreBadge } from "~/components/score-badge";
import { Badge } from "~/components/ui/badge";
import { Card } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { NativeSelect } from "~/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "~/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/tooltip";
import { comparePrices, type Compare, type Service } from "~/lib/api";
import { serviceApiId, serviceSlug } from "~/lib/catalog";
import { stateFor, statePath, type StateSummary } from "~/lib/states";
import {
  compareRows, DEFAULT_SORT, isPlaceholder, MARKETS, money, moneyRange, sortRows, summarize, titleCase,
  type Filters, type Range, type Setting, type Sort, type SortKey, type Summary,
} from "~/lib/summary";
import { cn } from "~/lib/utils";

// The pre-rendered page carries a compact table (every hospital's summary with no filters),
// enough for search engines and a first look; the browser then loads every plan's price.
type CompactRow = {
  ccn: string; name?: string; city?: string; county?: string; score_pct?: number;
  insurerMedian: number | null; insurerRange: Range; cash: Range; gross: Range; dollarPrices: number;
};
type PageData = { state: StateSummary; service: Service; note: string; compact: CompactRow[]; full: Compare | null };

const NO_FILTERS: Filters = { county: "", setting: "any", market: "", payer: "" };

async function fetchCompare(code: string, slug: string): Promise<[StateSummary, Compare]> {
  const state = stateFor(code);
  const id = serviceApiId(slug);
  if (!state || !id) throw data("Not found", { status: 404 });
  try {
    return [state, await comparePrices(state.code, serviceSlug(id))]; // normalized: "CPT-73721" -> "cpt-73721"
  } catch {
    throw data("Not found", { status: 404 });
  }
}

function compact(c: Compare): CompactRow[] {
  return c.hospitals
    .map((row) => ({ row, summary: summarize(row, NO_FILTERS) }))
    .sort(compareRows)
    .map(({ row: { hospital: h }, summary: s }) => ({
      ccn: h.ccn, name: h.name, city: h.city, county: h.county, score_pct: h.score_pct,
      insurerMedian: s.insurerMedian, insurerRange: s.insurerRange, cash: s.cash, gross: s.gross,
      dollarPrices: s.dollarPrices,
    }));
}

export async function loader({ params }: Route.LoaderArgs): Promise<PageData> {
  const [state, c] = await fetchCompare(params.state, params.slug);
  return { state, service: c.service, note: c.note, compact: compact(c), full: null };
}

export async function clientLoader({ params }: Route.ClientLoaderArgs): Promise<PageData> {
  const [state, c] = await fetchCompare(params.state, params.slug);
  return { state, service: c.service, note: c.note, compact: compact(c), full: c };
}
clientLoader.hydrate = true as const;

const serviceName = (s: Service) => s.cms_description ?? titleCase(s.description);
const codeLabel = (s: Service) => `${s.code_type === "MS-DRG" ? "MS-DRG" : "CPT/HCPCS"} ${s.code}`;

export const meta: Route.MetaFunction = ({ loaderData }) => {
  if (!loaderData) return [{ title: "Service not found | Clear Healthcare Prices" }];
  const s = loaderData.service;
  const name = loaderData.state.name;
  const priced = loaderData.compact.filter((r) => r.insurerMedian != null);
  const low = priced.length ? Math.min(...priced.map((r) => r.insurerMedian!)) : null;
  return [
    { title: `${serviceName(s)} (${codeLabel(s)}) prices at ${name} hospitals | Clear Healthcare Prices` },
    {
      name: "description",
      content: `Compare ${serviceName(s).toLowerCase()} prices at ${s.hospitals} ${name} hospitals` +
        (low != null ? `, from ${money(low)} (insurer median)` : "") + ". Cash, list and insurer prices from hospitals' own files.",
    },
  ];
};

function readFilters(p: URLSearchParams): Filters {
  return {
    county: p.get("county") ?? "",
    setting: (p.get("setting") as Setting) ?? "any",
    market: p.get("market") ?? "",
    payer: p.get("payer") ?? "",
  };
}

const ALL = "all";

export default function ServicePage({ loaderData }: Route.ComponentProps) {
  const { state, service: s, full, note } = loaderData;
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);

  const set = (patch: Partial<Filters>) => {
    const f = { ...filters, ...patch };
    const next = new URLSearchParams();
    if (f.county) next.set("county", f.county);
    if (f.setting !== "any") next.set("setting", f.setting);
    if (f.market) next.set("market", f.market);
    if (f.payer) next.set("payer", f.payer);
    setParams(next, { replace: true, preventScrollReset: true });
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
        <Link to={`${statePath(state)}/services`} className="hover:text-foreground">{state.name} services</Link>
        <span aria-hidden className="mx-2">/</span>
        <span className="text-foreground">{serviceName(s)}</span>
      </nav>
      <header className="mt-4">
        <h1 className="text-3xl font-semibold tracking-tight text-balance">{serviceName(s)}</h1>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Badge variant="secondary" className="font-mono">{codeLabel(s)}</Badge>
          {s.cms_shoppable_id != null && <Badge variant="outline">CMS shoppable service</Badge>}
          <span>Priced by {s.hospitals} {state.name} hospital{s.hospitals === 1 ? "" : "s"}</span>
          {s.cms_description && <span>Hospitals bill it as “{s.description}”</span>}
        </div>
      </header>

      {full ? (
        <Interactive data={full} state={state} filters={filters} set={set} />
      ) : (
        <StaticTable rows={loaderData.compact} />
      )}
      <p className="mt-6 text-sm text-muted-foreground">{note}</p>
    </div>
  );
}

function Explainer() {
  return (
    <div className="mt-8 grid gap-3 text-sm text-muted-foreground sm:grid-cols-3">
      {[
        ["Insurer median", "The middle of the prices this hospital lists for each insurer and plan. Your plan's price may be higher or lower."],
        ["Cash price", "The discounted price for paying yourself, without insurance."],
        ["List price", "The hospital's full chargemaster price, before any discount. Few people pay it."],
      ].map(([t, d]) => (
        <p key={t}><span className="font-medium text-foreground">{t}.</span> {d}</p>
      ))}
    </div>
  );
}

function StaticTable({ rows }: { rows: CompactRow[] }) {
  return (
    <>
      <Explainer />
      <NoCashNotice total={rows.length} missing={rows.filter((r) => !r.cash).length} />
      <Card className="mt-3 py-0">
        <Table>
          <PriceTableHead />
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.ccn}>
                <TableCell className="min-w-40 whitespace-normal pl-5"><HospitalName {...r} /></TableCell>
                <TableCell className="text-right tabular font-medium">
                  {money(r.insurerMedian)}
                  <CashOnPhones cash={r.cash} />
                </TableCell>
                <TableCell className="hidden text-right tabular text-muted-foreground md:table-cell">{moneyRange(r.insurerRange)}</TableCell>
                <TableCell className="hidden text-right tabular sm:table-cell"><StandardPrice range={r.cash} /></TableCell>
                <TableCell className="hidden text-right tabular text-muted-foreground lg:table-cell"><StandardPrice range={r.gross} /></TableCell>
                <TableCell className="hidden pr-5 sm:table-cell"><ScoreBadge score={r.score_pct} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </>
  );
}

const SORT_LABELS: Record<SortKey, [string, string, string]> = {
  // column, then how the row count describes each direction
  median: ["Insurer median", "lowest insurer median first", "highest insurer median first"],
  range: ["Insurer range", "lowest insurer price first", "highest low-end insurer price first"],
  cash: ["Cash", "lowest cash price first", "highest cash price first"],
  gross: ["List price", "lowest list price first", "highest list price first"],
  score: ["Transparency", "least transparent first", "most transparent first"],
};

function sortDescription(sort: Sort): string {
  return SORT_LABELS[sort.key][sort.dir === "asc" ? 1 : 2];
}

// The static (pre-rendered) table has no sort; the interactive one passes sort and onSort.
function PriceTableHead({ sort, onSort }: { sort?: Sort; onSort?: (key: SortKey) => void }) {
  const head = (key: SortKey, className: string) => (
    <SortableHead key={key} column={key} className={className} sort={sort} onSort={onSort} />
  );
  return (
    <TableHeader>
      <TableRow>
        <TableHead className="pl-5">Hospital</TableHead>
        {head("median", "text-right")}
        {head("range", "hidden text-right md:table-cell")}
        {head("cash", "hidden text-right sm:table-cell")}
        {head("gross", "hidden text-right lg:table-cell")}
        {head("score", "hidden pr-5 sm:table-cell")}
      </TableRow>
    </TableHeader>
  );
}

function SortableHead({ column, className, sort, onSort }: {
  column: SortKey; className: string; sort?: Sort; onSort?: (key: SortKey) => void;
}) {
  const label = SORT_LABELS[column][0];
  if (!sort || !onSort) return <TableHead className={className}>{label}</TableHead>;
  const active = sort.key === column;
  const Icon = !active ? ArrowUpDown : sort.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead
      className={className}
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        className="inline-flex items-center gap-1 rounded hover:text-primary focus-visible:outline-2 focus-visible:outline-ring"
      >
        {label}
        <Icon aria-hidden className={cn("size-3.5", active ? "text-primary" : "text-muted-foreground/60")} />
      </button>
    </TableHead>
  );
}

// Phones have no room for a Cash column; the cash price goes under the insurer median.
function CashOnPhones({ cash }: { cash: Range }) {
  if (!cash) return null;
  return <span className="block text-xs font-normal text-muted-foreground sm:hidden">Cash {moneyRange(cash)}</span>;
}

// A hospital's own cash or list price. Many files leave both blank for a procedure.
function StandardPrice({ range }: { range: Range }) {
  if (range) return <>{moneyRange(range)}</>;
  return <span className="text-xs text-muted-foreground">Unpublished</span>;
}

// Without this, blank Cash and List price columns read as missing data. They're blank in
// the hospitals' own files: a procedure charged as separate items (room, supplies, recovery)
// often has one price only in insurer contracts.
function NoCashNotice({ total, missing }: { total: number; missing: number }) {
  if (missing === 0) return null;
  return (
    <div className="mt-3 flex gap-2.5 rounded-lg border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
      <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
      <p className="text-pretty">
        <span className="font-medium text-foreground">
          {missing === total
            ? `None of ${total === 1 ? "this hospital" : `these ${total} hospitals`} publish${total === 1 ? "es" : ""} a cash price for this service.`
            : `${missing} of these ${total} hospitals don't publish a cash price for this service.`}
        </span>{" "}
        Their price files list only what each insurer pays and leave the cash and list price
        blank, often because the hospital charges a procedure as separate items (the room,
        supplies, recovery). Ask the hospital for a self-pay estimate.
      </p>
    </div>
  );
}

function HospitalName({ ccn, name, city }: { ccn: string; name?: string; city?: string }) {
  return (
    <span className="block min-w-0">
      <Link to={`/hospitals/${ccn}`} className="font-medium hover:text-primary hover:underline">{titleCase(name)}</Link>
      <span className="block text-sm text-muted-foreground">{titleCase(city)}</span>
    </span>
  );
}

function Interactive({ data: d, state, filters, set }: {
  data: Compare; state: StateSummary; filters: Filters; set: (patch: Partial<Filters>) => void;
}) {
  const counties = [...new Set(d.hospitals.map((h) => h.hospital.county ?? ""))].filter(Boolean).sort();
  const markets = [...new Set(d.hospitals.flatMap((h) => h.prices.map((p) => p.market ?? "")))].filter((m) => m in MARKETS);
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT);
  const rows = sortRows(
    d.hospitals
      .filter((h) => !filters.county || h.hospital.county === filters.county)
      .map((row) => ({ row, summary: summarize(row, filters) })),
    sort,
  );
  // Same column again flips the order; a new column starts cheapest (or best score) first.
  const onSort = (key: SortKey) =>
    setSort((s) => s.key === key
      ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
      : { key, dir: key === "score" ? "desc" : "asc" });

  return (
    <>
      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Area">
          <NativeSelect value={filters.county || ALL} onChange={(e) => set({ county: e.target.value === ALL ? "" : e.target.value })}>
            <option value={ALL}>All of {state.name}</option>
            {counties.map((c) => <option key={c} value={c}>{titleCase(c)} County</option>)}
          </NativeSelect>
        </Field>
        <Field label="Setting">
          <NativeSelect value={filters.setting} onChange={(e) => set({ setting: e.target.value as Setting })}>
            <option value="any">Inpatient or outpatient</option>
            <option value="outpatient">Outpatient</option>
            <option value="inpatient">Inpatient</option>
          </NativeSelect>
        </Field>
        <Field label="Insurance type">
          <NativeSelect value={filters.market || ALL} onChange={(e) => set({ market: e.target.value === ALL ? "" : e.target.value })}>
            <option value={ALL}>Any insurance</option>
            {markets.map((m) => <option key={m} value={m}>{MARKETS[m]}</option>)}
          </NativeSelect>
        </Field>
        <Field label="Insurer or plan">
          <Input type="search" placeholder="e.g. Aetna, BCBS" value={filters.payer} onChange={(e) => set({ payer: e.target.value })} />
        </Field>
      </div>
      <Explainer />

      {rows.length === 0 ? (
        <Card className="mt-6 px-6 py-10 text-center text-muted-foreground">
          No hospital {filters.county ? `in ${titleCase(filters.county)} County ` : ""}publishes a price for this service.
          {filters.county && <> <button className="text-primary hover:underline" onClick={() => set({ county: "" })}>Show all of {state.name}</button>.</>}
        </Card>
      ) : (
        <>
          <p className="mt-6 text-sm text-muted-foreground" aria-live="polite">
            {rows.length} hospital{rows.length === 1 ? "" : "s"}, {sortDescription(sort)}
          </p>
          <NoCashNotice total={rows.length} missing={rows.filter((r) => !r.summary.cash).length} />
          <Card className="mt-3 py-0">
            <Table>
              <PriceTableHead sort={sort} onSort={onSort} />
              <TableBody>
                {rows.map(({ row, summary }) => (
                  <HospitalRow key={row.hospital.ccn} row={row} summary={summary} />
                ))}
              </TableBody>
            </Table>
          </Card>
        </>
      )}
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5 text-sm font-medium">
      {label}
      {children}
    </label>
  );
}

function HospitalRow({ row, summary }: { row: Compare["hospitals"][number]; summary: Summary }) {
  const [open, setOpen] = useState(false);
  const h = row.hospital;
  const detailId = `detail-${h.ccn}`;
  const count = summary.prices.length;
  return (
    <Fragment>
      <TableRow
        className={cn(count > 0 && "cursor-pointer", open && "border-b-0 bg-muted/40")}
        onClick={(e) => {
          // The whole row opens the plan list; its link and button do their own thing.
          if (count > 0 && !(e.target as HTMLElement).closest("a, button")) setOpen(!open);
        }}
      >
        <TableCell className="min-w-40 whitespace-normal pl-5">
          <HospitalName ccn={h.ccn} name={h.name} city={h.city} />
          {count > 0 && (
            <button
              type="button"
              aria-expanded={open}
              aria-controls={detailId}
              onClick={() => setOpen(!open)}
              className="mt-1 inline-flex items-center gap-1 rounded text-xs font-medium text-primary hover:underline"
            >
              {open ? "Hide" : "See"} {count} insurer price{count === 1 ? "" : "s"}
              <ChevronDown aria-hidden className={cn("size-3.5 transition-transform", open && "rotate-180")} />
            </button>
          )}
        </TableCell>
        <TableCell className="text-right tabular font-medium">
          {money(summary.insurerMedian)}
          <CashOnPhones cash={summary.cash} />
        </TableCell>
        <TableCell className="hidden text-right tabular text-muted-foreground md:table-cell">{moneyRange(summary.insurerRange)}</TableCell>
        <TableCell className="hidden text-right tabular sm:table-cell"><StandardPrice range={summary.cash} /></TableCell>
        <TableCell className="hidden text-right tabular text-muted-foreground lg:table-cell"><StandardPrice range={summary.gross} /></TableCell>
        <TableCell className="hidden pr-5 sm:table-cell"><ScoreBadge score={h.score_pct} /></TableCell>
      </TableRow>
      {open && (
        <TableRow id={detailId} className="bg-muted/40 hover:bg-muted/40">
          <TableCell colSpan={6} className="whitespace-normal px-5 pb-5 pt-0">
            <PlanPrices summary={summary} />
          </TableCell>
        </TableRow>
      )}
    </Fragment>
  );
}

function PlanPrices({ summary }: { summary: Summary }) {
  if (summary.prices.length === 0) {
    return <p className="py-3 text-sm text-muted-foreground">No insurer prices match these filters.</p>;
  }
  return (
    <>
    {summary.placeholders > 0 && (
      <p className="pb-2 text-xs text-muted-foreground text-pretty">
        {summary.placeholders} of these {summary.placeholders === 1 ? "is a placeholder" : "are placeholders"} of
        $1 or less, which files use for “paid as part of a case rate”. They aren't real prices, so
        they're left out of the median and range.
      </p>
    )}
    <div className="overflow-x-auto rounded-md border bg-card">
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr className="border-b">
            <th className="px-3 py-2 font-medium">Insurer</th>
            <th className="px-3 py-2 font-medium">Plan</th>
            <th className="hidden px-3 py-2 font-medium sm:table-cell">Type</th>
            <th className="hidden px-3 py-2 font-medium sm:table-cell">Setting</th>
            <th className="px-3 py-2 text-right font-medium">Price</th>
          </tr>
        </thead>
        <tbody>
          {summary.prices.map((p, i) => (
            <tr key={i} className="border-b last:border-0">
              <td className="px-3 py-2">{p.group ?? p.payer}</td>
              <td className="px-3 py-2 text-muted-foreground">{p.plan}</td>
              <td className="hidden px-3 py-2 text-muted-foreground sm:table-cell">{MARKETS[p.market ?? ""] ?? ""}</td>
              <td className="hidden px-3 py-2 capitalize text-muted-foreground sm:table-cell">{p.setting}</td>
              <td className="px-3 py-2 text-right tabular">
                {isPlaceholder(p) ? <span className="text-muted-foreground">{money(p.amount)} <span className="text-xs">placeholder</span></span>
                  : p.type === "negotiated_dollar" ? money(p.amount)
                  : p.type === "negotiated_percentage" ? `${p.amount ?? "?"}% of charges`
                  : (
                    <Tooltip>
                      <TooltipTrigger className="inline-flex items-center gap-1 text-muted-foreground">
                        Formula <Info aria-hidden className="size-3.5" />
                      </TooltipTrigger>
                      <TooltipContent className="max-w-xs">{p.algorithm ?? "Priced by a formula the file describes."}</TooltipContent>
                    </Tooltip>
                  )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
