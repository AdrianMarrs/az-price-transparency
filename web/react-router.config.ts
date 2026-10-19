import { mkdirSync } from "node:fs";
import { setDefaultAutoSelectFamily } from "node:net";
import { dirname } from "node:path";

import type { Config } from "@react-router/dev/config";

import pages from "./app/data/prerender.json" with { type: "json" };

// A static site: no server at request time. Every page below is rendered to HTML at build
// time (so search engines and link previews see real content): each state's pages, its
// featured services that it prices, and every hospital with a profile (prerender.json, from
// scripts/build-data.mjs). Any other URL loads the app shell from __spa-fallback.html and
// renders in the browser.
//
// Pre-rendering requests each page from a preview server in this same process. Rendering a
// big page keeps the process busy, and Node's 250 ms per-address connect timer ("happy
// eyeballs") then gives up on localhost's IPv6 address, where the server is, for IPv4,
// where it isn't: connect ETIMEDOUT ::1 / ECONNREFUSED 127.0.0.1 failed one page in
// several thousand. One address, no timer.
setDefaultAutoSelectFamily(false);

export default {
  ssr: false,
  prerender: {
    paths: () => {
      const paths = [
        "/",
        "/methods",
        ...Object.entries(pages.services).flatMap(([state, slugs]) => {
          const st = `/${state.toLowerCase()}`;
          return [st, `${st}/services`, `${st}/hospitals`, ...slugs.map((slug) => `${st}/services/${slug}`)];
        }),
        ...pages.hospitals.map((ccn) => `/hospitals/${ccn}`),
      ];
      // Run concurrently, React Router can write a page's .data file (/tx/services/x.data)
      // before anything has made its folder, and fails (ENOENT); so make them all first.
      for (const dir of new Set(paths.map((p) => dirname(`build/client${p}`)))) mkdirSync(dir, { recursive: true });
      return paths;
    },
    // About 9,000 pages, each fetching its data file from the live site: one at a time
    // took about 40 minutes. CloudFront's busy answers are retried (app/lib/api.ts).
    concurrency: 16,
  },
} satisfies Config;
