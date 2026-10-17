// Writes the small data files the site is built from (run before `vite build` and dev):
//
//   app/data/hospitals.json          every in-scope Arizona hospital, with its profile from the
//                                    API (score, type, address): the hospital list, the search
//                                    box's hospital and city results, and one pre-rendered page each
//   app/data/featured-services.json  CMS's 70-odd "shoppable" services, pre-rendered as pages
//                                    and listed on the home page by category
//
// Hospitals come from warehouse/seeds/hospitals.csv (federal hospitals are out of scope);
// services from warehouse/seeds/shoppable_services.csv. Profiles are read from the live API
// (VITE_API_URL), the same cached responses the browser gets.

import { mkdir, readFile, writeFile } from "node:fs/promises";

const SEEDS = new URL("../../warehouse/seeds/", import.meta.url);
const OUT = new URL("../app/data/", import.meta.url);
const API = (process.env.VITE_API_URL ?? (await envLocal())).replace(/\/$/, "");

async function envLocal() {
  const text = await readFile(new URL("../.env.local", import.meta.url), "utf8").catch(() => "");
  const url = text.match(/^VITE_API_URL=(.+)$/m)?.[1]?.trim();
  if (!url) throw new Error("Set VITE_API_URL (or put it in web/.env.local)");
  return url;
}

// RFC 4180 CSV: quoted fields may hold commas, doubled quotes and newlines.
export function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const [header, ...body] = rows.filter((r) => r.some(Boolean));
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""])));
}

// "CPT/HCPCS" 73721 -> "cpt-73721" (a URL path segment); the API's id is "cpt-hcpcs:73721".
export const serviceSlug = (codeType, code) =>
  `${codeType === "MS-DRG" ? "drg" : "cpt"}-${code.toLowerCase()}`;

async function profile(ccn) {
  for (let attempt = 1; ; attempt++) {
    const response = await fetch(`${API}/providers/${ccn}`);
    if (response.ok) return response.json();
    if (response.status === 404) return null;
    if (attempt === 3) throw new Error(`/providers/${ccn}: HTTP ${response.status}`);
    await new Promise((r) => setTimeout(r, 1000 * attempt));
  }
}

async function main() {
  const seed = parseCsv(await readFile(new URL("hospitals.csv", SEEDS), "utf8"))
    .filter((h) => h.federally_run !== "true");
  const hospitals = [];
  for (let i = 0; i < seed.length; i += 8) { // a few at a time: polite to the API
    const batch = await Promise.all(seed.slice(i, i + 8).map(async (h) => {
      const p = (await profile(h.ccn)) ?? {};
      return {
        ccn: h.ccn,
        name: h.name,
        address: h.address,
        city: h.city,
        zip: h.zip.slice(0, 5),
        county: h.county,
        hospital_type: h.hospital_type,
        ownership: h.ownership,
        score_pct: p.score_pct ?? null,
        rules_checked: p.rules_checked ?? null,
        services: p.services ?? 0,
        price_file_status: p.price_file_status ?? null,
      };
    }));
    hospitals.push(...batch);
  }
  hospitals.sort((a, b) => a.name.localeCompare(b.name));

  const services = parseCsv(await readFile(new URL("shoppable_services.csv", SEEDS), "utf8")).map(
    (s) => ({
      slug: serviceSlug(s.code_type, s.code),
      id: `${s.code_type === "MS-DRG" ? "ms-drg" : "cpt-hcpcs"}:${s.code.toLowerCase()}`,
      code: s.code,
      code_type: s.code_type,
      category: s.category,
      description: s.description,
      cms_shoppable_id: Number(s.service_id),
    }),
  );

  await mkdir(OUT, { recursive: true });
  await writeFile(new URL("hospitals.json", OUT), JSON.stringify(hospitals, null, 1) + "\n");
  await writeFile(new URL("featured-services.json", OUT), JSON.stringify(services, null, 1) + "\n");
  console.log(`${hospitals.length} hospitals, ${services.length} featured services -> app/data/`);
}

if (import.meta.url === `file:///${process.argv[1].replaceAll("\\", "/").replace(/^\//, "")}`) {
  await main();
}
