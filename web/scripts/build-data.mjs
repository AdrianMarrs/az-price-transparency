// Writes the data files the site is built from (run before `vite build` and dev):
//
//   app/data/states.json             each state with data: name and counts, for the state
//                                    picker and each state's home page; and which state each
//                                    CCN prefix belongs to (a CCN's first two digits name its
//                                    state), so a hospital page finds its state's data
//   app/data/prerender.json          the pages to pre-render: every hospital with a profile,
//                                    and each state's featured services that it prices
//   public/catalog/<st>.json         one state's hospitals with their profile (score, type), for
//                                    its hospital list, search box and home page; and which
//                                    featured services it prices
//   public/catalog/hospitals.json    every hospital's name, city and state, for the search box
//                                    on pages that aren't about one state
//   app/data/featured-services.json  CMS's 70-odd "shoppable" services, pre-rendered as pages
//                                    and listed on each state's home page by category
//
// Hospitals come from warehouse/seeds/hospitals.csv, federal hospitals left out as out of
// scope; a state is on the site if its data files exist (serving/export_static.py writes
// them). Services come from warehouse/seeds/shoppable_services.csv. Profiles and service
// lists are read from the live site's data files (VITE_DATA_URL), as the browser reads them.

import { mkdir, readFile, writeFile } from "node:fs/promises";

const SEEDS = new URL("../../warehouse/seeds/", import.meta.url);
const OUT = new URL("../app/data/", import.meta.url);
const CATALOG = new URL("../public/catalog/", import.meta.url);
const DATA = `${(process.env.VITE_DATA_URL ?? (await envLocal())).replace(/\/$/, "")}/data`;
const PARALLEL = 16; // files fetched at a time

async function envLocal() {
  const text = await readFile(new URL("../.env.local", import.meta.url), "utf8").catch(() => "");
  const url = text.match(/^VITE_DATA_URL=(.+)$/m)?.[1]?.trim();
  if (!url) throw new Error("Set VITE_DATA_URL (or put it in web/.env.local)");
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

// Names for the state picker; the data has two-letter codes only.
export const STATE_NAMES = {
  AK: "Alaska", AL: "Alabama", AR: "Arkansas", AZ: "Arizona", CA: "California", CO: "Colorado",
  CT: "Connecticut", DC: "District of Columbia", DE: "Delaware", FL: "Florida", GA: "Georgia",
  HI: "Hawaii", IA: "Iowa", ID: "Idaho", IL: "Illinois", IN: "Indiana", KS: "Kansas",
  KY: "Kentucky", LA: "Louisiana", MA: "Massachusetts", MD: "Maryland", ME: "Maine",
  MI: "Michigan", MN: "Minnesota", MO: "Missouri", MS: "Mississippi", MT: "Montana",
  NC: "North Carolina", ND: "North Dakota", NE: "Nebraska", NH: "New Hampshire",
  NJ: "New Jersey", NM: "New Mexico", NV: "Nevada", NY: "New York", OH: "Ohio", OK: "Oklahoma",
  OR: "Oregon", PA: "Pennsylvania", PR: "Puerto Rico", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VA: "Virginia", VT: "Vermont",
  WA: "Washington", WI: "Wisconsin", WV: "West Virginia", WY: "Wyoming",
  AS: "American Samoa", GU: "Guam", MP: "Northern Mariana Islands", VI: "U.S. Virgin Islands",
};

// A busy answer from CloudFront is retried after a growing pause.
const BUSY = new Set([429, 502, 503, 504]);

// A data file, or null when there's none (a missing file comes back as the app shell, HTML,
// not a 404: see app/lib/api.ts).
async function dataFile(path) {
  for (let attempt = 1; ; attempt++) {
    const response = await fetch(`${DATA}${path}`);
    if (response.ok) return response.headers.get("content-type")?.includes("json") ? response.json() : null;
    if (response.status === 404 || response.status === 403) return null;
    if (!BUSY.has(response.status) || attempt === 6) throw new Error(`${path}: HTTP ${response.status}`);
    await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
  }
}

// fn over items, PARALLEL at a time; results in the items' order.
async function mapParallel(items, fn) {
  const out = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: PARALLEL }, async () => {
    while (next < items.length) { const i = next++; out[i] = await fn(items[i]); }
  }));
  return out;
}

// Which state each CCN prefix belongs to; an error if the seed ever breaks that rule.
export function ccnPrefixes(hospitals) {
  const prefixes = {};
  for (const h of hospitals) {
    const prefix = h.ccn.slice(0, 2);
    if (prefixes[prefix] && prefixes[prefix] !== h.state) {
      throw new Error(`CCN prefix ${prefix} is in both ${prefixes[prefix]} and ${h.state}`);
    }
    prefixes[prefix] = h.state;
  }
  return prefixes;
}

async function main() {
  const seed = parseCsv(await readFile(new URL("hospitals.csv", SEEDS), "utf8"))
    .filter((h) => h.federally_run !== "true");
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

  // The states with data, and the featured services each prices (from its service list).
  const codes = [...new Set(seed.map((h) => h.state))].sort();
  const lists = await mapParallel(codes, (st) => dataFile(`/${st.toLowerCase()}/search.json`));
  const priced = Object.fromEntries(codes.flatMap((st, i) => {
    if (!lists[i]) return [];
    const ids = new Set(lists[i].map((s) => s.id));
    return [[st, services.filter((s) => ids.has(s.id)).map((s) => s.slug)]];
  }));
  const states = Object.keys(priced);

  const inScope = seed.filter((h) => states.includes(h.state));
  const profiles = await mapParallel(inScope, (h) => dataFile(`/${h.state.toLowerCase()}/providers/${h.ccn}.json`));
  const hospitals = inScope.map((h, i) => {
    const p = profiles[i] ?? {};
    return {
      ccn: h.ccn,
      name: h.name,
      address: h.address,
      city: h.city,
      state: h.state,
      zip: h.zip.slice(0, 5),
      county: h.county,
      hospital_type: h.hospital_type,
      ownership: h.ownership,
      score_pct: p.score_pct ?? null,
      rules_checked: p.rules_checked ?? null,
      services: p.services ?? 0,
      price_file_status: p.price_file_status ?? null,
    };
  }).sort((a, b) => a.name.localeCompare(b.name));

  const summary = states.map((st) => {
    const hs = hospitals.filter((h) => h.state === st);
    const scored = hs.filter((h) => h.score_pct != null);
    return {
      code: st,
      name: STATE_NAMES[st] ?? st,
      hospitals: hs.length,
      withPrices: hs.filter((h) => h.services > 0).length,
      scored: scored.length,
      meetsAll: scored.filter((h) => h.score_pct === 100).length,
    };
  }).sort((a, b) => a.name.localeCompare(b.name));

  await mkdir(OUT, { recursive: true });
  await mkdir(CATALOG, { recursive: true });
  const write = (url, value) => writeFile(url, JSON.stringify(value) + "\n");
  await write(new URL("states.json", OUT), { states: summary, prefixes: ccnPrefixes(seed) });
  await write(new URL("prerender.json", OUT), {
    hospitals: inScope.filter((_, i) => profiles[i] != null).map((h) => h.ccn),
    services: priced,
  });
  for (const st of states) {
    await write(new URL(`${st.toLowerCase()}.json`, CATALOG), {
      hospitals: hospitals.filter((h) => h.state === st),
      featured: priced[st],
    });
  }
  // [ccn, name, city, state] for every hospital: small enough to fetch on a first search
  await write(new URL("hospitals.json", CATALOG), hospitals.map((h) => [h.ccn, h.name, h.city, h.state]));
  await writeFile(new URL("featured-services.json", OUT), JSON.stringify(services, null, 1) + "\n");
  console.log(`${states.length} states, ${hospitals.length} hospitals, ${services.length} featured services -> app/data/, public/catalog/`);
}

if (import.meta.url === `file:///${process.argv[1].replaceAll("\\", "/").replace(/^\//, "")}`) {
  await main();
}
