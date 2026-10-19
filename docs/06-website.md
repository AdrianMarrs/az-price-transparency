# 06 · The website

How clearhealthcareprices.com is put together as of October 2026. There is no server code and no database. The site is a set of files in S3, served by CloudFront. It has two parts that are built and deployed separately:

- **The app** (`web/`): a React app. Its pages are rendered ahead of time where possible, and the browser renders the rest. Deployed by `scripts/deploy_site.py`.
- **The data** (`data/<state>/…`): gzip-compressed JSON files that `serving/export_static.py` writes from the DuckDB warehouse. They go to the same bucket, so the browser fetches them from the site's own origin.

A deploy of the app never touches `data/`, and an export of the data never touches the app.

```
 warehouse (DuckDB) ──export_static.py──▶ s3://site/data/az/…   ┐
                                                                 ├─▶ CloudFront ─▶ browser
 web/ ──npm run build──▶ build/client ──deploy_site.py──▶ s3://site/…  ┘
```

## Stack

- React 19 and React Router 8 in framework mode, with `ssr: false` and pre-rendering (`web/react-router.config.ts`).
- Vite 8 and Tailwind 4, with radix-ui primitives wrapped in `app/components/ui` (badge, button, card, input, native select, separator, skeleton, table, tabs, tooltip).
- lucide icons, and the Inter font served from the site itself.
- Tests run on vitest (`npm test`). Type checks run as part of every build (`react-router typegen && tsc`).

## Pages

`web/app/routes.ts`:

| URL | Route | Pre-rendered | Data |
| --- | --- | --- | --- |
| `/` | `home.tsx` | yes | built in: featured services, hospitals |
| `/services` | `services.tsx` | yes | built in: featured services by category |
| `/services/:slug` | `service.tsx` | featured services only (74) | `data/az/services/<slug>.json` |
| `/hospitals` | `hospitals.tsx` | yes | built in: hospital list |
| `/hospitals/:ccn` | `hospital.tsx` | every hospital (95) | `data/az/providers/<ccn>.json` |
| `/search?q=` | `search.tsx` | no | `data/az/search.json`, plus the built-in hospitals and cities |
| `/methods` | `methods.tsx` | yes | built in: the rules (`lib/rules.ts`) |
| anything else | `not-found.tsx` | no | — |

That makes 4 + 95 + 74 = 173 pre-rendered pages. Any other URL is served the app shell (`__spa-fallback.html`), and the page renders in the browser. A service that isn't featured, such as one found through search, works this way.

What each page does:

- **Home** has the search box, common services, "who follows the rules" (hospitals by transparency score), and how it works.
- **Services** lists the featured services by category, with a search box.
- **Service** is the main comparison. Each row is one hospital, showing the insurer median, insurer range, cash and gross prices, and the hospital's score.
  - The columns sort; the default is the median, low to high (`lib/summary.ts`).
  - Filters for county, setting (inpatient or outpatient), market (commercial, Medicare Advantage, Medicaid…) and payer live in the URL (`?county=&setting=&market=&payer=`), so a filtered view can be linked to.
  - Filtering happens in the browser, over one file per service. Prices of $1 or less are treated as placeholders and left out (`PLACEHOLDER_MAX`), and a hospital that publishes nothing for the service is shown as "Unpublished".
  - The pre-rendered page carries a compact table, with every hospital's unfiltered summary, for search engines and a fast first view. The browser then loads the full file and its plan-by-plan prices.
- **Hospital** shows the profile (address, type, ownership, the price file and its status), a "Price transparency" card listing the rules the hospital passed or failed (`lib/rules.ts`), and its CMS shoppable services with negotiated median and cash price.
- **Hospitals** is the list, filtered by name, city and type and sorted, all held in the URL (`?q=&city=&type=&sort=`).
- **Search** finds services, hospitals and cities.
- **Methods** describes how the data is made and its limits.

## Shared pieces

- `app/root.tsx` holds the document layout: skip link, `SiteHeader`, `<main>`, `SiteFooter` (`components/site-chrome.tsx`, with the "Clear Healthcare Prices" logo). It also has `HydrateFallback`, a skeleton shown while a page that wasn't pre-rendered loads, and `ErrorBoundary`, the 404 and error page.
- `components/search-box.tsx` is the search box on the home, services and search pages. It suggests hospitals and cities instantly, from the built-in list, and services after the search list has loaded.
- `components/score-badge.tsx` shows a hospital's "N% transparent" badge.

## Data in the app

There are two sources.

**Built in at build time.** `web/scripts/build-data.mjs` runs first in `npm run build` and writes two files:

- `app/data/hospitals.json`: the in-scope Arizona hospitals (`STATE = "AZ"`, not federally run), each with fields from its profile file.
- `app/data/featured-services.json`: CMS's shoppable services that the site features, with categories.

`lib/catalog.ts` wraps both. It provides hospital lookup by CCN, the city list, word-prefix search over hospitals and cities ("st jo" finds St Joseph's), and the mapping from service slug to ID (`cpt-73721` ↔ `cpt-hcpcs:73721`, `drg-470` ↔ `ms-drg:470`; colons can't appear in file names).

**Fetched at run time.** `lib/api.ts` reads `data/az/…`:

| File | Used by | Contents |
| --- | --- | --- |
| `search.json` | search, search box | every service (about 13,000; 350 KB compressed), fetched once and searched in the browser |
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

1. `build-data.mjs` writes the built-in data above. It reads profile files from `VITE_DATA_URL`.
2. Type check.
3. `react-router build` pre-renders the 173 pages, fetching their data from `VITE_DATA_URL`.
4. `scripts/externalize-inline-scripts.mjs` moves every inline `<script>` that React Router writes (hydration data, the app's entry module, scroll restoration) into its own content-hashed file under `assets/inline/`. That lets the Content Security Policy stay `script-src 'self'`. It also removes `async` from module scripts, because React 19 skips `<script async src>` when hydrating, which fails hydration with React error #418.

The result is `web/build/client`. `docker/web.Dockerfile` builds the same output in a container: `--target site`, with `VITE_DATA_URL` required. CI runs `npm test` and `npm run build`, then the container build.

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
- **Error responses:** a 403 or 404 from S3 is served `/__spa-fallback.html` with a 200, cached for 60 seconds. The app then renders the page, or its own 404.
- **Response headers:**
  - HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`.
  - CSP: `default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'`. Nothing is loaded from another origin, so there are no fonts, analytics or scripts from elsewhere.

## Deploy

`uv run python scripts/deploy_site.py` (after the build) uploads `web/build/client`. The bucket and distribution come from `SITE_BUCKET` and `SITE_DISTRIBUTION_ID`, or else from `terraform output`.

- **Caching:** files under `assets/` have a content hash in their name and are cached for a year (`immutable`). Pages and their `.data` files keep their names between builds, so they are sent `no-cache`, and the deploy clears them from CloudFront.
- **Deleting:** files no longer in the build are deleted, except anything under `data/`.

## Local development

- **`npm run dev`:** the Vite dev server. It proxies `/data` to `VITE_DATA_URL`, which defaults to the live site, so no local data is needed. Set `VITE_POLL=1` when running in Docker on a bind mount (the `dev` target of `docker/web.Dockerfile`).
- **`node scripts/serve-build.mjs [port]`:** serves `build/client` the way CloudFront does, to check a build before it's deployed.
  - It uses the same file lookup and fallback to the app shell.
  - It sends the same security headers, including the CSP, so anything the policy would block fails locally too.
  - It passes `/data/` through to the live site.

## Tests

- `app/lib/*.test.ts`:
  - `api.test.ts`: retries, not-found handling, service search.
  - `catalog.test.ts`: hospital and city search, slugs.
  - `summary.test.ts`: medians, placeholders, filters, sorting.
  - `encoding.test.ts`: catches text garbled from UTF-8 read back as Windows-1252.
- `scripts/externalize-inline-scripts.test.mjs`.
- On the Python side, `tests/test_export_static.py` covers the data files, including a two-state warehouse.

## Limits and open questions

- **Arizona only.** `api.ts` reads `data/az/`, `build-data.mjs` keeps `STATE = "AZ"`, and page text says "AZ". The national pass exports data for every state to `data/<state>/` ([05](05-national.md)), but no page reads it yet.
  - Multi-state pages need a URL scheme, for example `/az/hospitals/030006` or a state chosen on the page. That decision is still open.
  - They also need a decision on how much to pre-render: 5,000 hospitals' pages instead of 95.
  - `search.json` would be per state, or the search would need narrowing first.
- **Data is frozen.** The refresh schedules are created turned off, so the files stay as the initial pass left them ([05](05-national.md)).
- **Search is all in the browser.** That's fine at 13,000 services in one state. One list for the whole country would be too large to download.
