// The site's own lists, written by scripts/build-data.mjs: CMS's shoppable services (built
// in), each state's hospitals (public/catalog/<st>.json) and every hospital's name, for
// searching (public/catalog/hospitals.json). The hospital lists are fetched when a page or
// the search box needs them, once each; at build time (pre-rendering) they're read from disk.

import featured from "~/data/featured-services.json";

export type FeaturedService = (typeof featured)[number];
export const featuredServices: FeaturedService[] = featured;
export const categories = [...new Set(featuredServices.map((s) => s.category))];

export type HospitalSummary = {
  ccn: string;
  name: string;
  address: string;
  city: string;
  state: string;
  zip: string;
  county: string;
  hospital_type: string;
  ownership: string;
  score_pct: number | null;
  rules_checked: number | null;
  services: number;
  price_file_status: string | null;
};

export type StateCatalog = { hospitals: HospitalSummary[]; featured: string[] };

// One hospital in the search index: [ccn, name, city, state].
export type IndexEntry = [string, string, string, string];

async function catalogFile<T>(name: string): Promise<T> {
  if (import.meta.env.SSR) {
    const { readFile } = await import("node:fs/promises");
    return JSON.parse(await readFile(`public/catalog/${name}`, "utf8"));
  }
  const response = await fetch(`/catalog/${name}`);
  if (!response.ok || !response.headers.get("content-type")?.includes("json")) {
    throw new Error(`/catalog/${name}: HTTP ${response.status}`);
  }
  return response.json();
}

const cache = new Map<string, Promise<unknown>>();
function cached<T>(name: string): Promise<T> {
  let p = cache.get(name) as Promise<T> | undefined;
  if (!p) {
    p = catalogFile<T>(name).catch((e) => { cache.delete(name); throw e; }); // try again next time
    cache.set(name, p);
  }
  return p;
}

export const stateCatalog = (state: string) => cached<StateCatalog>(`${state.toLowerCase()}.json`);
export const hospitalIndex = () => cached<IndexEntry[]>("hospitals.json");

// "cpt-73721" (URL) <-> "cpt-hcpcs:73721" (API). Colons can't be in a file name, and
// pre-rendered pages are files.
export const serviceSlug = (apiId: string) => apiId.replace(/^cpt-hcpcs:/, "cpt-").replace(/^ms-drg:/, "drg-");
export function serviceApiId(slug: string): string | null {
  const m = /^(cpt|drg)-([a-z0-9]+)$/.exec(slug.toLowerCase());
  return m ? `${m[1] === "drg" ? "ms-drg" : "cpt-hcpcs"}:${m[2]}` : null;
}

export type City = { city: string; county: string; hospitals: number };

// A state's cities, most hospitals first.
export function citiesOf(hospitals: HospitalSummary[]): City[] {
  return Object.values(
    hospitals.reduce<Record<string, City>>((acc, h) => {
      acc[h.city] ??= { city: h.city, county: h.county, hospitals: 0 };
      acc[h.city].hospitals++;
      return acc;
    }, {}),
  ).sort((a, b) => b.hospitals - a.hospitals || a.city.localeCompare(b.city));
}

const words = (text: string) => text.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);

// Every query word must start a word of the text: "st jo" finds "St Joseph's Hospital".
export function matches(query: string, text: string): boolean {
  const have = words(text);
  return words(query).every((q) => have.some((w) => w.startsWith(q)));
}

export function searchHospitals<T extends { name: string; city: string }>(list: T[], query: string, limit = 6): T[] {
  if (query.trim().length < 2) return [];
  return list.filter((h) => matches(query, `${h.name} ${h.city}`)).slice(0, limit);
}

export function searchCities(list: City[], query: string, limit = 3): City[] {
  if (query.trim().length < 2) return [];
  return list.filter((c) => matches(query, c.city)).slice(0, limit);
}

export const indexEntry = ([ccn, name, city, state]: IndexEntry) => ({ ccn, name, city, state });
