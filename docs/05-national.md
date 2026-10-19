# 05 · Every state

Arizona's 95 hospitals were found partly by hand ([02](02-arizona.md)). For 5,228 hospitals that doesn't scale, so national discovery is automatic, and this note measures how far that gets. The data is kept as the initial pass leaves it: every refresh schedule is created turned off (October 2026).

## Finding the price files

`ingest/national/discover.py`, cached under `data/national/` so a rerun only fetches what's new:

1. **Hospitals:** CMS's Hospital General Information file, every state and territory: 5,419 hospitals, 5,228 in scope once federally run ones (VA, Indian Health Service, tribal, military) are left out as in Arizona.
2. **Websites:** CMS's list has none. The homepage DoltHub's community dataset has for a CCN (1,425 hospitals), else Wikidata's official website for a hospital in the same state with a near-exact, unambiguous name that also names its city or shares three distinctive words (521 more).
3. **cms-hpt.txt:** fetched once from each of the 1,054 websites (16 at a time), plus about 130 health systems' sites (`ingest/national/systems.txt`), whose files list many hospitals each. The same rules as Arizona: a plain 403 is retried once as a browser, and bot challenges are recorded, never worked around.
4. **Matching:** a hospital takes the entry in its own website's file whose location name matches its name best, on distinctive words (so "Banner Desert Medical Center" isn't "Banner Del E. Webb Medical Center"), or the only entry when the file lists one. An exact match wins over a longer name ("Good Samaritan Hospital", not "Good Samaritan Hospital-Mission Oaks"), and failing all that, a name may match in full without its brand: the part before " - " ("KAISER FOUNDATION HOSPITAL - VACAVILLE" is "Vacaville Medical Center" in Kaiser's file) or a word in the website's host ("Mercy" on mercy.com). A hospital with no match there may take an entry from any file fetched, but only a near-exact, unambiguous match that names its city or shares three distinctive words (`system_match`). "Holy Cross" alone once matched a hospital in another state; that's what the second condition is for.

| Result | Hospitals |
| --- | ---: |
| Found on its own website (`found`, `found_browser_ua_only`, `found_manual_copy`) | 1,105 |
| Found in a health system's file (`system_match`) | 416 |
| **Price file found** | **1,521 (29%)** |
| No website known | 2,955 |
| Website's file doesn't list it (`no_matching_location`) | 216 |
| Refused (`http_403`, `blocked_bot_challenge`) | 285 |
| Other errors (404s, timeouts, non-text answers) | the rest |

Wikidata raised the count from 1,127 (22%) to 1,415, and the exact-name and brand rules to 1,521. By state it runs from 63% (Utah, 32 of 51) to 2% (Puerto Rico); Arizona is 46% (44 of 95), against 84 of 95 found with the hand work.

**Precision:** all 44 Arizona hospitals found automatically got the same price file as the hand-checked seed, and samples of the new matches elsewhere (12 through Wikidata, 15 through the name rules) were all the right hospital. A `system_match` keeps that status in the seed: the file is real, but it wasn't confirmed at the hospital's own website root, so the cms-hpt.txt rule isn't counted as passed.

## Seeds

`ingest/national/seeds.py` writes `warehouse/seeds/hospitals.csv` for every state and `hospital_sources.csv` with Arizona's hand-checked rows kept as they are and the automatic matches for everyone else: 1,561 hospitals with a price file URL, 84 of them in Arizona. Rebuilt with every hospital, the warehouse writes the same Arizona site files as the Arizona-only build.

## Running it

`ingest/pipeline.py --state UT ...` downloads, parses and writes to the lake, then builds the warehouse and the states' site files ([03](03-cloud.md#hospital-pipeline-on-fargate-spot)). In the cloud it runs as a Fargate task (4 vCPU, 30 GB, x86): hospitals on Spot, with the states split across parallel tasks, and the warehouse build (`--warehouse-only`) on regular capacity, since a Spot interruption late in a build loses all of it. The weekly schedule exists but is turned off.

## The first national pass (October 2026)

Every hospital outside Arizona with a price file (Arizona's were already in the lake):

| Step | Hospitals |
| --- | ---: |
| In scope, outside Arizona | 5,133 |
| Price file found | 1,477 |
| Downloaded | 1,378 |
| Download failed | 94 |
| Over the 5 GB download limit | 5 |
| Parsed (one of them only partly) | 1,279 |
| Parsed, but no service codes the site can use | 49 |
| Deferred as too large to parse in memory (28 JSON, 9 CSV, 8 zip) | 45 |
| Parse failed | 2 |

The download failures:

- **HTTP 403, 78 hospitals.** 62 of them answer a program that sends a browser's User-Agent from home, but not from AWS: Cloudflare and similar services block the cloud's addresses. Two that were checked (410006, 410012) download from a laptop. The other 16 refuse any program.
- **HTTP 404, 12 hospitals.** The cms-hpt.txt file points at a file that's gone.
- **Out of memory, 2 hospitals.** The worker was killed.
- **Timed out, 2 hospitals.**

Over 5 GB: 140281 (IL), 150074 (IN), 240010 (MN, 13.4 GB), 330078 and 330279 (NY). The two parse failures: 150011 (IN), a zip with no CSV or JSON in it, and 260001 (MO, Mercy Joplin), which took over the 60-minute limit for one file.

**The warehouse:** built from every state's prices, it ran out of memory on `marts.price_summary`, on a 30 GB task and then on a 120 GB one. Exact quartiles keep every price of a group in memory, outside DuckDB's memory limit and with no spilling to disk. Next, `serving.srv_service_prices` filled a 100 GB disk with spill files. Both are now built in 16 buckets of services, one statement each (`warehouse/macros/bucket_hooks.sql`), and the build passes on the 30 GB task with a 200 GB disk: about 1 hour for dbt, then 1 hour for the export. Arizona's tables are identical either way.

**The export:** 711,756 files for 51 states (with DC and Puerto Rico; not Arizona, which was already there, or the four other territories, which have no hospitals with prices). Most states have 10,000 to 16,000 files, but Colorado and New York have about 68,000 each. Every in-scope hospital has a profile, with or without prices.

**Cost:** about $12 in all. Roughly $7 was the hospital tasks, and $5 was the warehouse runs (three of them failed) plus 702,188 S3 uploads at $0.005 per 1,000. A rerun with the same data uploads almost nothing, since unchanged files are skipped.

By state ("with prices" counts hospitals with at least one usable price in the lake):

| State | In scope | Price file found | With prices |
| --- | ---: | ---: | ---: |
| AK | 18 | 8 | 8 (44%) |
| AL | 95 | 28 | 27 (28%) |
| AR | 88 | 24 | 15 (17%) |
| AZ | 95 | 82 | 69 (73%) |
| CA | 368 | 98 | 90 (24%) |
| CO | 94 | 37 | 36 (38%) |
| CT | 34 | 12 | 7 (21%) |
| DC | 9 | 2 | 2 (22%) |
| DE | 12 | 1 | 1 (8%) |
| FL | 214 | 39 | 39 (18%) |
| GA | 144 | 31 | 30 (21%) |
| HI | 22 | 10 | 10 (45%) |
| IA | 115 | 38 | 31 (27%) |
| ID | 47 | 11 | 11 (23%) |
| IL | 188 | 53 | 44 (23%) |
| IN | 146 | 47 | 44 (30%) |
| KS | 137 | 49 | 46 (34%) |
| KY | 98 | 25 | 25 (26%) |
| LA | 157 | 25 | 24 (15%) |
| MA | 78 | 12 | 11 (14%) |
| MD | 54 | 14 | 8 (15%) |
| ME | 34 | 2 | 2 (6%) |
| MI | 144 | 49 | 47 (33%) |
| MN | 132 | 42 | 33 (25%) |
| MO | 116 | 41 | 28 (24%) |
| MS | 106 | 21 | 18 (17%) |
| MT | 59 | 10 | 10 (17%) |
| NC | 114 | 36 | 31 (27%) |
| ND | 44 | 4 | 4 (9%) |
| NE | 91 | 31 | 25 (27%) |
| NH | 27 | 11 | 11 (41%) |
| NJ | 77 | 25 | 24 (31%) |
| NM | 39 | 12 | 12 (31%) |
| NV | 44 | 6 | 5 (11%) |
| NY | 183 | 44 | 29 (16%) |
| OH | 189 | 56 | 48 (25%) |
| OK | 127 | 28 | 20 (16%) |
| OR | 60 | 23 | 23 (38%) |
| PA | 179 | 72 | 59 (33%) |
| PR | 58 | 1 | 1 (2%) |
| RI | 12 | 7 | 4 (33%) |
| SC | 64 | 16 | 16 (25%) |
| SD | 56 | 26 | 10 (18%) |
| TN | 117 | 29 | 25 (21%) |
| TX | 462 | 147 | 120 (26%) |
| UT | 51 | 32 | 32 (63%) |
| VA | 93 | 44 | 43 (46%) |
| VT | 16 | 6 | 5 (31%) |
| WA | 98 | 28 | 28 (29%) |
| WI | 137 | 54 | 51 (37%) |
| WV | 51 | 5 | 3 (6%) |
| WY | 29 | 5 | 5 (17%) |
| **All** | **5,222** | **1,559** | **1,350 (26%)** |

## Still to do

- **Coverage:** 2,910 hospitals outside Arizona have no known website; finding more is the biggest lever. 214 more have a website whose file doesn't name them in a way the matching accepts.
- **Blocked from the cloud:** the 62 hospitals that refuse AWS's addresses could be downloaded from a home connection and imported into the lake.
- **The site:** the data files are written per state (`data/<state>/`); the pages still show Arizona only ([06](06-website.md#limits-and-open-questions)).
- **Large files:** 45 deferred and 5 over the download limit, until there's a streaming parser.
