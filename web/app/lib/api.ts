// Reads the site's data: static JSON files that serving/export_static.py writes next to the
// site, under /data/<state>/. Used in the browser (same origin, so a relative URL) and, for
// pre-rendered pages, at build time in Node, which needs the site's address (VITE_DATA_URL).
// In development Vite proxies /data to the live site (vite.config.ts).

const STATE = "az";
const BASE = typeof window === "undefined" ? (import.meta.env.VITE_DATA_URL ?? "").replace(/\/$/, "") : "";

export type Service = {
  id: string;
  key: string;
  code: string;
  code_type: string;
  description: string;
  cms_shoppable_id?: number;
  cms_description?: string;
  hospitals: number;
};

export type Price = {
  payer?: string;
  plan?: string;
  group?: string;
  market?: string;
  setting?: string;
  type: string;
  method?: string;
  amount?: number;
  algorithm?: string;
  bundled?: boolean;
  n: number;
};

export type Hospital = {
  ccn: string;
  name?: string;
  city?: string;
  county?: string;
  score_pct?: number;
  hospital_type?: string;
};

export type HospitalPrices = {
  hospital: Hospital;
  plans: number;
  standard: Price[];
  prices: Price[];
};

export type Compare = {
  service: Service;
  hospitals: HospitalPrices[];
  note: string;
};

export type Profile = Hospital & {
  address?: string;
  zip?: string;
  ownership?: string;
  mrf_url?: string;
  rules_checked?: number;
  rules_passed?: number;
  failed_rules?: string;
  services?: number;
  price_file_status?: string;
  shoppable?: ShoppableSummary[];
  shoppable_services?: number;
  note: string;
};

// One CMS shoppable service at one hospital, as summarized on its profile.
export type ShoppableSummary = {
  service_key: string; // "CPT/HCPCS:73721"
  description: string;
  cms_shoppable_id: number;
  negotiated_median?: number;
  cash?: number;
  plans: number;
};

// A build pre-renders 170 pages from these files; a busy answer from CloudFront is retried
// after a growing pause. GETs are safe to repeat.
const BUSY = new Set([429, 502, 503, 504]);
export const RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

export async function fetchWithRetry(url: string, signal?: AbortSignal, delays = RETRY_DELAYS_MS) {
  for (let attempt = 0; ; attempt++) {
    const response = await fetch(url, { signal });
    if (!BUSY.has(response.status) || attempt >= delays.length) return response;
    await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
  }
}

export class NotFound extends Error {}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetchWithRetry(`${BASE}/data/${STATE}${path}`, signal);
  // A missing file comes back as the app shell (CloudFront's fallback for unknown paths),
  // with a 200, so the type tells a data file from a missing one.
  if (response.status === 404 || response.status === 403 || !response.headers.get("content-type")?.includes("json")) {
    throw new NotFound(path);
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

// Search runs in the browser over the whole service list (about 13,000 services, 350 KB
// compressed), fetched once on the first search.
export type SearchService = Service & { terms?: string };
let serviceList: Promise<SearchService[]> | null = null;

export function searchServices(q: string): Promise<Service[]> {
  serviceList ??= get<SearchService[]>("/search.json").catch((e) => {
    serviceList = null; // try again next time
    throw e;
  });
  return serviceList.then((list) => findServices(list, q));
}

// The same rules the API's search used: every word must appear in the code, description or
// plain-English terms; CMS shoppable services first, then the most widely priced.
export function findServices(list: SearchService[], q: string, limit = 25): Service[] {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const text = (s: SearchService) =>
    `${s.code} ${s.description} ${s.cms_description ?? ""} ${s.terms ?? ""}`.toLowerCase();
  return list
    .filter((s) => { const t = text(s); return words.every((w) => t.includes(w)); })
    .sort((a, b) =>
      Number(a.cms_shoppable_id == null) - Number(b.cms_shoppable_id == null)
      || b.hospitals - a.hospitals || a.id.localeCompare(b.id))
    .slice(0, limit);
}

// Filters are applied in the browser, so one file serves every filter choice.
export const comparePrices = (slug: string, signal?: AbortSignal) =>
  get<Compare>(`/services/${slug}.json`, signal);

export const hospitalProfile = (ccn: string, signal?: AbortSignal) =>
  get<Profile>(`/providers/${ccn}.json`, signal);
