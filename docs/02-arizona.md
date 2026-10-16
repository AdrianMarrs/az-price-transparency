# 02 · Every Arizona hospital

Phase 2 took the Pima County pipeline statewide and put it on a schedule. Of Arizona's 95 in-scope hospitals, 82 price files were obtained (three of them downloaded by hand) and all 82 parse (14.6M prices, all loaded into Postgres); 39 hospitals pass every compliance rule we can check, and 68 publish usable insurer prices. Dagster now runs the pipeline weekly, one partition per hospital.

Data downloaded and checked 2026-10-16. The full compliance report is [docs/reports/arizona-compliance-2026-10-16.md](reports/arizona-compliance-2026-10-16.md).

## Finding 95 price files

The CMS hospital list doesn't include websites, so each had to be found ([`warehouse/seeds/hospital_websites.csv`](../warehouse/seeds/hospital_websites.csv), column `website_source`):

| How the website was found | Hospitals |
| --- | ---: |
| Known health-system or hospital domain (Banner, HonorHealth, CommonSpirit, ...) | 40 |
| DoltHub's community hospital dataset (homepage by CCN) | 30 |
| Web search | 23 |
| Not found | 2 |

Every candidate was verified by fetching its `cms-hpt.txt`, which caught two wrong guesses with similar names: a Louisiana health system for Little Colorado Medical Center and a Virginia hospital for Wickenburg. System files cover many hospitals at once: CommonSpirit's lists 72 locations in six states, Banner's 31.

| Result | Hospitals |
| --- | ---: |
| Found by a program | 50 |
| Found, but only when claiming to be a browser (Banner, Mayo) | 19 |
| Found by hand after a bot challenge or 403 blocked the program (Carondelet, Abrazo, Northern Arizona Healthcare, Valleywise, Onvida, Arizona Spine & Joint, City of Hope) | 13 |
| Found, but `cms-hpt.txt` isn't in CMS's format | 2 |
| No `cms-hpt.txt` (404) or a web page instead | 7 |
| File doesn't list this hospital | 2 |

Notable: East Valley ER & Hospital's `cms-hpt.txt` names a different hospital, in Oklahoma; HonorHealth Tempe is missing from HonorHealth's file; The Guidance Center serves its price file itself at `/cms-hpt.txt`; Destiny Springs' file points to a price file that returns 404. Valleywise's file puts a blank line between every field, so the parser now starts a new location at each location-name line rather than at blank lines.

## Downloading and parsing

- **Downloads:** 79 of 84 files with a known URL. Three of the misses are the price files themselves refusing programs (HTTP 403 behind a bot challenge): Northern Arizona Healthcare's two zips (Flagstaff, Verde Valley) and City of Hope's. Those three were downloaded by hand in a browser and imported with `download --import-file <ccn> <path>`, which stores them like any download but records `access = manual_download`, so they still fail the download rule while their contents are checked. The fourth miss is Destiny Springs' 404. Mayo Clinic Arizona's file is **21.5 GB**, so the downloader skips files over 5 GB until there is a streaming parser.
- **Parsing:** all 82 files read (target was 90%): 69 with service-code prices, 13 that bill only by revenue code (psychiatric hospitals and the four Exceptional Community Hospitals). New handling added for this: formats detected from content rather than file names (many URLs have none), zip files, a fallback reader for a CSV polars rejected (Kingman Regional, line breaks inside values), dropping rows that become identical after cleaning (536.13 vs 536.130), and a per-file outcome log (`data/parsed/parse_report.csv`, not in Git).
- **Output:** 14,637,772 prices from 69 hospitals, all loaded into Postgres (`LOAD_COUNTIES` now defaults to every county). The database is 7.9 GB with the warehouse built.

## Compliance

Nine rules per hospital ([`ingest/hospitals/compliance.py`](../ingest/hospitals/compliance.py)), scored by dbt in `marts.hospital_compliance_scores`. Highlights:

- **No insurer prices at all:** the three Carondelet hospitals (St. Joseph's, St. Mary's, Holy Cross), Abrazo Scottsdale and the four Exceptional Community Hospitals.
- **Mostly percentages or formulas, not dollars:** six hospitals, as low as 3% in dollars (White Mountain Regional).
- **CMS's own validator** (`@cmsgov/hpt-validator-cli` 1.10.8) agreed on five spot-checked files. It checks format, not substance: it passes a file with no insurer prices. It also corrected one of our findings: CMS accepts M/D/YYYY dates in CSV files.

## Insurer names

Statewide files use 820 insurer names. `dim_payer_plans` maps each payer + plan to a parent company (exact alias, else an ordered pattern) and a market (from patterns on payer and plan text, so a "Work Comp" plan under a commercial payer counts as workers' comp). Coverage: parent company for 90% of price rows, market for 80%. A dbt unit test pins the precedence rules.

### The nine rules

| Rule | Passes when |
| --- | --- |
| `cms_hpt_lists_hospital` | `cms-hpt.txt` at the website root names this hospital's price file |
| `cms_hpt_machine_readable` | ...and a program can read it as-is: no bot challenge, no browser-only access, well-formed |
| `price_file_downloads` | The price file it points to downloads (files too large for us to read still pass) |
| `price_file_parses` | The file reads as a CMS template file |
| `version_stated` | The header states a template version |
| `header_fields_present` | Hospital name, date, version, location, address, license, type 2 NPI and attestation are filled in |
| `payer_prices_present` | The whole file (every code) has at least one payer-specific negotiated charge |
| `mostly_dollar_prices` | At least half of unbundled insurer prices are dollar amounts |
| `updated_within_12_months` | `last_updated_on` is within the last year |

A rule that can't be checked (no file obtained) is recorded as not checked, not as a pass, and `score_pct` counts only checked rules alongside how many that was.

## Orchestration

**Why Dagster over Airflow.** Dagster models the pipeline as *assets* (the tables and files it produces) rather than tasks, which matches how this project is described: each step writes something you can look at. It reads the dbt project directly and turns every dbt model into an asset wired to its upstream Python assets, partitions per hospital are built in, and it runs locally with one command. Airflow is more common in job postings and is the alternative if a target employer uses it; the asset code would port to Airflow tasks, the dbt wiring would need Cosmos or similar.

**Partitioning by hospital.** The unit of failure is one hospital's file, so the partition is the hospital (95 static partitions from the seed), not time. A file that fails to download or parse fails only its own run; the weekly schedule sends one run per hospital, and the local run queue caps concurrency at 3.

**Failure handling.**

- Within a file: rows that fail validation go to a rejects file with the reason; the file still loads.
- Within a run: a file that can't be parsed raises in its own partition; files too large to read are recorded as deferred instead of failing.
- Across runs: asset checks warn on a 30% row-count swing or a file older than a year; a run-failure sensor posts to a webhook; and the Redis lock stops overlapping runs downloading the same hospital.
- Compliance findings (a blocked or missing file) are data, not pipeline failures: they are recorded and scored, and the run succeeds.

[`orchestration/definitions.py`](../orchestration/definitions.py) defines the pipeline as Dagster assets:

```
hospital list -> price-file sources -> [per hospital] download -> parse -> load
                                       payer names, compliance checks -> dbt models
```

- One partition per hospital, so a bad file fails only its own run.
- A Redis lock per hospital prevents two runs downloading the same file (tested by holding the lock by hand).
- Asset checks flag a row count moving more than 30% between runs and a file older than a year.
- A failure sensor posts to `ALERT_WEBHOOK_URL` when one is set; for now none is, so failures are only logged.
- Weekly schedules (Mondays, Arizona time): discovery at 6:00, one run per hospital at 7:00, warehouse build at 11:00.

```
$env:DAGSTER_HOME = "$PWD\.dagster_home"
uv run dagster dev -m orchestration.definitions
```

## Decisions

- **All of Arizona is loaded into Postgres**, not just Pima County.
- **Blocked files are fetched by hand** in a browser, never by automating past a bot challenge: `cms-hpt.txt` copies (contacts removed) go into `ingest/hospitals/manual_cms_hpt/` and are recorded as `found_manual_copy`, which still fails the machine-readable rule; price files are imported with `--import-file` and still fail the download rule.
- **The browser user-agent fallback stays**, and is recorded as `found_browser_ua_only`.
- **Alerts: log only for now.** The webhook is wired but unset.
- **Rehabilitation and long-term acute care hospitals are left out**; the CMS list doesn't include them.
- **Hospitals are named** in the report and any write-up.

## Open items

- **Hand-downloaded price files** (Flagstaff, Verde Valley, City of Hope) don't refresh on the weekly run; re-download them when the hospitals post new ones.
- **Mayo Clinic Arizona** needs a streaming parser (Phase 4 skill).
- **Insurer names:** the last 20% of price rows have no market yet; needs a review pass.
