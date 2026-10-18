// Turns one hospital's prices for a service into the numbers the table shows.
// Pure functions, so they're tested on their own (summary.test.ts).

import type { HospitalPrices, Price } from "./api";

export type Setting = "any" | "outpatient" | "inpatient";

export type Filters = {
  county: string; // "" = all of Arizona
  setting: Setting;
  market: string; // "" = every market
  payer: string; // matches payer, plan or parent company
};

export type Range = { low: number; high: number } | null;

export type Summary = {
  cash: Range;
  gross: Range;
  insurerMedian: number | null;
  insurerRange: Range;
  dollarPrices: number; // insurer prices given in dollars (placeholders not counted)
  placeholders: number; // $1-or-less stand-ins: see isPlaceholder
  otherPrices: number; // insurer prices given as a percentage or formula
  prices: Price[]; // the insurer prices that pass the filters
};

export const MARKETS: Record<string, string> = {
  commercial: "Commercial",
  medicare_advantage: "Medicare Advantage",
  medicare_ffs: "Medicare",
  medicaid: "Medicaid (AHCCCS)",
  exchange: "Marketplace",
  military_va: "Military / VA",
  workers_comp: "Workers' comp",
};

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function range(values: number[]): Range {
  if (values.length === 0) return null;
  return { low: Math.min(...values), high: Math.max(...values) };
}

// Some files list an insurer's price for a procedure as $1 (or $0.01): a stand-in meaning
// "paid as part of a case rate", not a price anyone pays. Counted, they made Abrazo's
// colonoscopy median $239 instead of $1,321, so they're shown but left out of the numbers.
export const PLACEHOLDER_MAX = 1;

export function isPlaceholder(price: Price): boolean {
  return price.type === "negotiated_dollar" && price.amount != null && price.amount <= PLACEHOLDER_MAX;
}

// A price listed for "both" settings applies to outpatient and inpatient alike.
export function inSetting(price: Price, setting: Setting): boolean {
  return setting === "any" || !price.setting || price.setting === setting || price.setting === "both";
}

export function matchesFilters(price: Price, f: Filters): boolean {
  if (!inSetting(price, f.setting)) return false;
  if (f.market && price.market !== f.market) return false;
  if (f.payer) {
    const text = `${price.payer ?? ""} ${price.plan ?? ""} ${price.group ?? ""}`.toLowerCase();
    if (!text.includes(f.payer.toLowerCase())) return false;
  }
  return true;
}

export function summarize(row: HospitalPrices, f: Filters): Summary {
  const standard = row.standard.filter((p) => inSetting(p, f.setting));
  const amounts = (type: string) =>
    standard.filter((p) => p.type === type && p.amount != null).map((p) => p.amount!);
  const prices = row.prices.filter((p) => matchesFilters(p, f));
  const placeholders = prices.filter(isPlaceholder).length;
  const dollars = prices
    .filter((p) => p.type === "negotiated_dollar" && p.amount != null && !isPlaceholder(p))
    .map((p) => p.amount!);
  return {
    cash: range(amounts("discounted_cash")),
    gross: range(amounts("gross")),
    insurerMedian: median(dollars),
    insurerRange: range(dollars),
    dollarPrices: dollars.length,
    placeholders,
    otherPrices: prices.length - dollars.length - placeholders,
    prices,
  };
}

// Hospitals with insurer dollar prices first, cheapest median first; then the rest by name.
export function compareRows(
  a: { row: HospitalPrices; summary: Summary },
  b: { row: HospitalPrices; summary: Summary },
): number {
  const am = a.summary.insurerMedian;
  const bm = b.summary.insurerMedian;
  if (am != null && bm != null) return am - bm;
  if (am != null) return -1;
  if (bm != null) return 1;
  return (a.row.hospital.name ?? "").localeCompare(b.row.hospital.name ?? "");
}

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function money(value: number | null | undefined): string {
  return value == null ? "—" : usd.format(value);
}

export function moneyRange(r: Range): string {
  if (!r) return "—";
  return r.low === r.high ? money(r.low) : `${money(r.low)}–${money(r.high)}`;
}

export function titleCase(text: string | undefined): string {
  // Capitalize after a space, hyphen, slash or "(" only, so "ST JOSEPH'S" -> "St Joseph's".
  return (text ?? "")
    .toLowerCase()
    .replace(/(^|[\s\-/(])(\w)/g, (_, pre: string, c: string) => pre + c.toUpperCase());
}
