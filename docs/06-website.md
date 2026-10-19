# 06 · The website

How clearhealthcareprices.com is put together as of October 2026, with a section for every state. There is no server code and no database. The site is a set of files in S3, served by CloudFront. It has two parts that are built and deployed separately:

- **The app** (`web/`): a React app. Its pages are rendered ahead of time where possible, and the browser renders the rest. Deployed by `scripts/deploy_site.py`.
- **The data** (`data/<state>/…`): gzip-compressed JSON files that `serving/export_static.py` writes from the DuckDB warehouse. They go to the same bucket, so the browser fetches them from the site's own origin.

A deploy of the app never touches `data/`, and an export of the data never touches the app.

```
 warehouse (DuckDB) ──export_static.py──▶ s3://site/data/<state>/…   ┐
                                                                      ├─▶ CloudFront ─▶ browser
 web/ ──npm run build──▶ build/client ──deploy_site.py──▶ s3://site/…       ┘
```

## Stack

- React 19 and React Router 8 in framework mode, with `ssr: false` and pre-rendering (`web/react-router.config.ts`).
- Vite 8 and Tailwind 4, with radix-ui primitives wrapped in `app/components/ui` (badge, button, card, input, native select, separator, skeleton, table, tabs, tooltip).
- lucide icons, and the Inter font served from the site itself.
- Tests run on vitest (`npm test`). Type checks run as part of every build (`react-router typegen && tsc`).

## Pages

Prices are compared within a state, so most pages belong to one: `/tx/services/cpt-73721` is a knee MRI at Texas hospitals. A hospital's page has no state in its URL, because its CCN is unique across the country and its first two digits name the state. `web/app/routes.ts`:

| URL | Route | Pre-rendered | Data |
| --- | --- | --- | --- |
| `/` | `home.tsx` | yes | built in: the states and their counts |
| `/:state` | `state.tsx` | every state (52) | the state's catalog |
| `/:state/services` | `services.tsx` | every state | built in: featured services; the catalog says which the state prices |
| `/:state/services/:slug` | `service.tsx` | each state's featured services that it prices (3,748) | `data/<st>/services/<slug>.json` |
| `/:state/hospitals` | `hospitals.tsx` | every state | the state's catalog |
| `/hospitals/:ccn` | `hospital.tsx` | every hospital with a profile (5,222) | `data/<st>/providers/<ccn>.json` |
| `/search?q=&state=` | `search.tsx` | no | the state's `search.json` and catalog; with no state, the hospital index |
| `/methods` | `methods.tsx` | yes | built in: the rules (`lib/rules.ts`) |
| `/services`, `/services/:slug`, `/hospitals` | `legacy.tsx` | no | none: Arizona's old addresses, redirected to `/az/…` |
| anything else | `not-found.tsx` | no | none |

That makes 9,128 pre-rendered pages. Any other URL is served the app shell (`__spa-fallback.html`), and the page renders in the browser. A service that isn't featured, such as one found through search, works this way. The 52 "states" are the 50 states, DC and Puerto Rico; the other four territories have no hospitals with prices yet.

What each page does:

- **Home** picks a state: a menu, and a grid showing how many of each state's hospitals publish prices we can read. Its search box finds hospitals and states.
- **A state's home** has the state's search box, common services (ones the state doesn't price are dimmed), "who follows the rules" (hospitals by transparency score), and its counts.
- **Services** lists the featured services by category, with a search box, and marks those no hospital in the state prices.
- **Service** is the main comparison. Each row is one hospital in the state, showing the insurer median, insurer range, cash and gross prices, and the hospital's score.
  - The columns sort; the default is the median, low to high (`lib/summary.ts`).
  - Filters for county, setting (inpatient or outpatient), market (commercial, Medicare Advantage, Medicaid…) and payer live in the URL (`?county=&setting=&market=&payer=`), so a filtered view can be linked to.
  - Filtering happens in the browser, over one file per service. Prices of $1 or less are treated as placeholders and left out (`PLACEHOLDER_MAX`), and a hospital that publishes nothing for the service is shown as "Unpublished".
  - The pre-rendered page carries a compact table, with every hospital's unfiltered summary, for search engines and a fast first view. The browser then loads the full file and its plan-by-plan prices.
- **Hospital** shows the profile (address, type, ownership, the price file and its status), a "Price transparency" card listing the rules the hospital passed or failed (`lib/rules.ts`), and its CMS shoppable services with negotiated median and cash price, linked to its state's service pages.
- **Hospitals** is a state's list, filtered by name, city and type and sorted, all held in the URL (`?q=&city=&type=&sort=`). The page is pre-rendered without them, so they apply once it has hydrated (`useHydrated` in `lib/utils.ts`); applying them during hydration fails it with React error #418.
- **Search** finds a state's services, hospitals and cities, or, with no state, hospitals anywhere and states.
- **Methods** describes how the data is made and its limits.

## Shared pieces

- `app/root.tsx` holds the document layout (skip link, `<main>`) and the page around it: `SiteHeader` and `SiteFooter` (`components/site-chrome.tsx`, with the "Clear Healthcare Prices" logo).
  - The header takes the page's state, from the URL or the hospital's CCN. Its links go to that state's services and hospitals, a chip names the state, and its search box searches it. On a page with no state, the links are "States" and "How it works".
  - The app component renders the header, not the layout, because the app shell is one file for every URL. The shell's own header (in `HydrateFallback`) has no state, so hydrating it anywhere matches.
  - `ErrorBoundary` is the 404 and error page.
- `components/search-box.tsx` is the search box. On a state's pages it suggests the state's hospitals and cities (from its catalog) and its services (from its `search.json`); elsewhere, hospitals anywhere (from the hospital index) and states. Each list is fetched on the first search that needs it.
- `components/score-badge.tsx` shows a hospital's "N% transparent" badge.

## Data in the app

There are three sources.

**Built in at build time.** `web/scripts/build-data.mjs` runs first in `npm run build` (about 80 seconds) and writes:

- `app/data/states.json`: each state with data, with its name and counts. A state is on the site if its `data/<st>/search.json` exists. The file also says which state each CCN prefix belongs to; the script checks that no prefix is in two states (there are 57 prefixes).
- `app/data/featured-services.json`: CMS's shoppable services that the site features, with categories.
- `app/data/prerender.json`: the pages to pre-render (not part of the app).

**The site's own catalogs.** Also from `build-data.mjs`, served with the app (`public/catalog/`):

- `<st>.json`: one state's in-scope hospitals (not federally run), each with fields from its profile file, and the featured services the state prices. Texas's is the largest, at 146 KB before compression.
- `hospitals.json`: every hospital's CCN, name, city and state (312 KB before compression), for searching on pages that aren't about one state.

`lib/states.ts` wraps `states.json`: a state by its URL code, a hospital's state from its CCN, and state search. `lib/catalog.ts` fetches the catalogs once each (at build time it reads them from disk). It also provides:

- the city list;
- word-prefix search over hospitals and cities ("st jo" finds St Joseph's);
- the mapping from service slug to ID: `cpt-73721` ↔ `cpt-hcpcs:73721`, `drg-470` ↔ `ms-drg:470`, because colons can't appear in file names.

None of the generated files are in git.

**Fetched at run time.** `lib/api.ts` reads a state's `data/<st>/…`:

| File | Used by | Contents |
| --- | --- | --- |
| `search.json` | search, search box | every service the state prices (Arizona: about 13,000; 350 KB compressed), fetched once and searched in the browser |
| `services/<slug>.json` | service page | every hospital's standard, cash and plan prices for one service |
| `providers/<ccn>.json` | hospital page | profile, compliance rules, shoppable service summaries |

How `api.ts` fetches:

- In the browser it uses a relative URL, which is same-origin. When pre-rendering in Node it prefixes `VITE_DATA_URL`.
- A busy answer (429 or 5xx from 502 up) is retried after 0.5, 1, 2, 4 and then 8 seconds.
- A missing file reaches CloudFront's fallback, which returns the app shell with a 200. So any answer that isn't JSON, like a 403 or 404, is a `NotFound`, which the routes turn into the 404 page.
- Service search requires every word to appear in the code, description or plain-English terms. CMS shoppable services come first, then the most widely priced services.

`export_static.py` writes the files gzip-compressed, without timestamps, so equal data gives equal bytes and a rerun uploads only what changed. They are uploaded with `Content-Encoding: gzip` and `Cache-Control: public, max-age=300, s-maxage=86400`, and CloudFront's copies of `data/<state>/*` are cleared after each export.

## Build

`npm run build` in `web/` runs four steps:

1. `build-data.mjs` writes the data above. It reads every state's service list and every hospital's profile from `VITE_DATA_URL`, 16 at a time.
2. Type check.
3. `react-router build` pre-renders the 9,128 pages, 16 at a time, fetching their data from `VITE_DATA_URL`: about 17 minutes on a laptop, against about 40 one at a time. Run concurrently, React Router can write a page's `.data` file before its folder exists, so `react-router.config.ts` makes the folders first. The config also turns off Node's per-address connect timer (happy eyeballs): the preview server React Router renders from runs in the same busy process, and the timer made about one request in several thousand give up on localhost's IPv6 address and fail on IPv4.
4. `scripts/externalize-inline-scripts.mjs` moves every inline `<script>` that React Router writes (hydration data, the app's entry module, scroll restoration) into its own content-hashed file under `assets/inline/`. That lets the Content Security Policy stay `script-src 'self'`. It also removes `async` from module scripts, because React 19 skips `<script async src>` when hydrating, which fails hydration with React error #418.

The result is `web/build/client`. `docker/web.Dockerfile` builds the same output in a container: `--target site`, with `VITE_DATA_URL` required. CI runs `npm run data`, then `npm test` (the catalog tests read Arizona's catalog), then `npm run build`, then the container build.

## Hosting

`infra/main/site.tf`:

- **S3 bucket:** private. CloudFront reads it through Origin Access Control, and the bucket isn't listable, so a missing object comes back as a 403.
- **CloudFront:**
  - `PriceClass_100`, IPv6 on, HTTPS only (HTTP redirects).
  - AWS's managed `CachingOptimized` policy, with compression on.
  - The domain's aliases are set once the domain is live.
- **Viewer-request function** (`site_router.js`):
  - Maps a page URL to its pre-rendered file: `/hospitals/030006` → `/hospitals/030006/index.html`. Paths with an extension pass through unchanged.
  - Sends any host other than the apex (www, the CloudFront name) a 301 to `https://clearhealthcareprices.com`, keeping the path and query.
  - Sends Arizona's old addresses a 301 to their new ones: `/services`, `/services/<slug>` and `/hospitals` go to `/az/…`. A hospital's page, `/hospitals/<ccn>`, didn't move.
- **Error responses:** a 403 or 404 from S3 is served `/__spa-fallback.html` with a 200, cached for 60 seconds. The app then renders the page, or its own 404.
- **Response headers:**
  - HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`.
  - CSP: `default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'`. Nothing is loaded from another origin, so there are no fonts, analytics or scripts from elsewhere.

## Deploy

`uv run python scripts/deploy_site.py` (after the build) uploads `web/build/client`, 32 files at a time. A build has about 20,000 files, because each pre-rendered page is an `index.html` and a `.data` file. The bucket and distribution come from `SITE_BUCKET` and `SITE_DISTRIBUTION_ID`, or else from `terraform output`.

- **Caching:** files under `assets/` have a content hash in their name and are cached for a year (`immutable`). Pages and their `.data` files keep their names between builds, so they are sent `no-cache`, and the deploy clears them from CloudFront.
- **Deleting:** files no longer in the build are deleted, except anything under `data/`.
- **Clearing CloudFront:** one invalidation of `/*`. That counts as a single path however many files it covers, and the first 1,000 paths a month are free.

## Local development

- **`npm run dev`:** the Vite dev server. It proxies `/data` to `VITE_DATA_URL`, which defaults to the live site, so no local data is needed. Set `VITE_POLL=1` when running in Docker on a bind mount (the `dev` target of `docker/web.Dockerfile`).
- **`node scripts/serve-build.mjs [port]`:** serves `build/client` the way CloudFront does, to check a build before it's deployed.
  - It uses the same file lookup and fallback to the app shell.
  - It sends the same security headers, including the CSP, so anything the policy would block fails locally too.
  - It passes `/data/` through to the live site.
  - It redirects Arizona's old addresses as CloudFront does.

## Tests

- `app/lib/*.test.ts`:
  - `api.test.ts`: retries, not-found handling, service search.
  - `catalog.test.ts`: hospital and city search over Arizona's catalog, slugs, states by URL code and by CCN, state search.
  - `summary.test.ts`: medians, placeholders, filters, sorting.
  - `encoding.test.ts`: catches text garbled from UTF-8 read back as Windows-1252.
- `scripts/externalize-inline-scripts.test.mjs`.
- On the Python side, `tests/test_export_static.py` covers the data files, including a two-state warehouse.

## Limits and open questions

- **Coverage varies by state.** A hospital without a price file we could read has a page with its score and no prices. In some states that's most of them ([05](05-national.md)).
- **Each state stands alone.** A service is compared within one state. There's no cross-state comparison, and searching for a service needs a state.
- **Data is frozen.** The refresh schedules are created turned off, so the files stay as the initial pass left them ([05](05-national.md)).
- **Search is all in the browser.** Each state's service list is fetched on its first search; one list for the whole country would be too large to download.
