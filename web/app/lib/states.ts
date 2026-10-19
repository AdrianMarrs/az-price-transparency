// The states on the site (those with data files), from app/data/states.json, which
// scripts/build-data.mjs writes. URLs use the lowercase code: /tx/services.

import data from "~/data/states.json";

export type StateSummary = (typeof data.states)[number];

export const states: StateSummary[] = data.states;

const byCode = new Map(states.map((s) => [s.code.toLowerCase(), s]));

// The state for a URL's code ("tx", any case), or undefined if it isn't on the site.
export const stateFor = (code: string | undefined) => (code ? byCode.get(code.toLowerCase()) : undefined);

// A CCN's first two digits name its state ("03" is Arizona). Undefined for a state that
// isn't on the site.
export function stateOfCcn(ccn: string | undefined): StateSummary | undefined {
  const code = ccn ? (data.prefixes as Record<string, string>)[ccn.slice(0, 2)] : undefined;
  return stateFor(code);
}

export const statePath = (s: StateSummary | string) => `/${(typeof s === "string" ? s : s.code).toLowerCase()}`;

export function searchStates(query: string, limit = 3): StateSummary[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  return states
    .filter((s) => s.code.toLowerCase() === q || s.name.toLowerCase().split(/\s+/).some((w) => w.startsWith(q))
      || s.name.toLowerCase().startsWith(q))
    .slice(0, limit);
}
