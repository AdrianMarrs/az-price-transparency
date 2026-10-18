# 05 · Every state

Arizona's 95 hospitals were found partly by hand ([02](02-arizona.md)). For 5,228 hospitals that doesn't scale, so national discovery is automatic, and this note measures how far that gets. The data is kept as the initial pass leaves it: every refresh schedule is created turned off (October 2026).

## Finding the price files

`ingest/national/discover.py`, cached under `data/national/` so a rerun only fetches what's new:

1. **Hospitals:** CMS's Hospital General Information file, every state and territory: 5,419 hospitals, 5,228 in scope once federally run ones (VA, Indian Health Service, tribal, military) are left out as in Arizona.
2. **Websites:** CMS's list has none. The homepage DoltHub's community dataset has for a CCN (1,425 hospitals), else Wikidata's official website for a hospital in the same state with a near-exact, unambiguous name that also names its city or shares three distinctive words (521 more).
3. **cms-hpt.txt:** fetched once from each of the 1,054 websites (16 at a time), plus about 130 health systems' sites (`ingest/national/systems.txt`), whose files list many hospitals each. The same rules as Arizona: a plain 403 is retried once as a browser, and bot challenges are recorded, never worked around.
4. **Matching:** a hospital takes the entry in its own website's file whose location name matches its name best, on distinctive words (so "Banner Desert Medical Center" isn't "Banner Del E. Webb Medical Center"), or the only entry when the file lists one. A hospital with no match there may take an entry from any file fetched, but only a near-exact, unambiguous match that names its city or shares three distinctive words (`system_match`). "Holy Cross" alone once matched a hospital in another state; that's what the second condition is for.

| Result | Hospitals |
| --- | ---: |
| Found on its own website (`found`, `found_browser_ua_only`, `found_manual_copy`) | 982 |
| Found in a health system's file (`system_match`) | 433 |
| **Price file found** | **1,415 (27%)** |
| No website known | 2,912 |
| Website's file doesn't list it (`no_matching_location`) | 320 |
| Refused (`http_403`, `blocked_bot_challenge`) | 282 |
| Other errors (404s, timeouts, non-text answers) | the rest |

Wikidata raised the count from 1,127 (22%) to 1,415. By state it runs from 63% (Utah, 32 of 51) to 2% (Puerto Rico); Arizona is 44% (42 of 95), against 84 of 95 found with the hand work.

**Precision:** all 42 Arizona hospitals found automatically got the same price file as the hand-checked seed, and a sample of 12 Wikidata matches elsewhere were all the right hospital. A `system_match` keeps that status in the seed: the file is real, but it wasn't confirmed at the hospital's own website root, so the cms-hpt.txt rule isn't counted as passed.

## Seeds

`ingest/national/seeds.py` writes `warehouse/seeds/hospitals.csv` for every state and `hospital_sources.csv` with Arizona's hand-checked rows kept as they are and the automatic matches for everyone else: 1,457 hospitals with a price file URL, 84 of them in Arizona. Rebuilt with every hospital, the warehouse writes the same Arizona site files as the Arizona-only build.

## Running it

`ingest/pipeline.py --state UT ...` downloads, parses and writes to the lake, then builds the warehouse and the states' site files ([03](03-cloud.md#hospital-pipeline-on-fargate-spot)). In the cloud it runs as a Fargate Spot task, defined but not yet created.

## Still to do

- **Coverage:** 2,912 hospitals have no known website; finding more is the biggest lever. 320 more have a website whose file doesn't name them in a way the matching accepts.
- **The site:** the data files are written per state (`data/<state>/`); the pages still show Arizona only.
- **Large files:** files over 3 GB (CSV) or 0.6 GB (JSON) are deferred, as in Arizona, until there's a streaming parser.
