// The site's built-in data: every in-scope hospital and CMS's shoppable services, written
// by scripts/build-data.mjs. Search over hospitals and cities happens here in the browser;
// services beyond the featured ones come from the API.

import featured from "~/data/featured-services.json";
import hospitalList from "~/data/hospitals.json";

export type HospitalSummary = (typeof hospitalList)[number];
export type FeaturedService = (typeof featured)[number];

export const hospitals: HospitalSummary[] = hospitalList;
export const featuredServices: FeaturedService[] = featured;

const byCcn = new Map(hospitals.map((h) => [h.ccn, h]));
export const hospital = (ccn: string) => byCcn.get(ccn);

// "cpt-73721" (URL) <-> "cpt-hcpcs:73721" (API). Colons can't be in a file name, and
// pre-rendered pages are files.
export const serviceSlug = (apiId: string) => apiId.replace(/^cpt-hcpcs:/, "cpt-").replace(/^ms-drg:/, "drg-");
export function serviceApiId(slug: string): string | null {
  const m = /^(cpt|drg)-([a-z0-9]+)$/.exec(slug.toLowerCase());
  return m ? `${m[1] === "drg" ? "ms-drg" : "cpt-hcpcs"}:${m[2]}` : null;
}

export const categories = [...new Set(featuredServices.map((s) => s.category))];

export type City = { city: string; county: string; hospitals: number };

export const cities: City[] = Object.values(
  hospitals.reduce<Record<string, City>>((acc, h) => {
    acc[h.city] ??= { city: h.city, county: h.county, hospitals: 0 };
    acc[h.city].hospitals++;
    return acc;
  }, {}),
).sort((a, b) => b.hospitals - a.hospitals || a.city.localeCompare(b.city));

const words = (text: string) => text.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);

// Every query word must start a word of the text: "st jo" finds "St Joseph's Hospital".
export function matches(query: string, text: string): boolean {
  const have = words(text);
  return words(query).every((q) => have.some((w) => w.startsWith(q)));
}

export function searchHospitals(query: string, limit = 6): HospitalSummary[] {
  if (query.trim().length < 2) return [];
  return hospitals.filter((h) => matches(query, `${h.name} ${h.city}`)).slice(0, limit);
}

export function searchCities(query: string, limit = 3): City[] {
  if (query.trim().length < 2) return [];
  return cities.filter((c) => matches(query, c.city)).slice(0, limit);
}
