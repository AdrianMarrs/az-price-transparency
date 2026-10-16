# 02 · Every Arizona hospital

Phase 2 took the Pima County pipeline statewide and put it on a schedule. Of Arizona's 95 in-scope hospitals, 72 price files were obtained and all 72 parse (11.8M prices); 39 hospitals pass every compliance rule we can check, and 59 publish usable insurer prices. Dagster now runs the pipeline weekly, one partition per hospital.

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
| Found by hand after a bot challenge blocked the program (Carondelet) | 3 |
| Found, but `cms-hpt.txt` isn't in CMS's format | 2 |
| Blocked by a bot challenge | 9 |
| No `cms-hpt.txt` (404) or a web page instead | 7 |
| File doesn't list this hospital | 2 |
| Access refused (403) | 1 |

Notable: East Valley ER & Hospital's `cms-hpt.txt` names a different hospital, in Oklahoma; HonorHealth Tempe is missing from HonorHealth's file; The Guidance Center serves its price file itself at `/cms-hpt.txt`; Destiny Springs' file points to a price file that returns 404.

## Downloading and parsing

- **Downloads:** 72 of 74 files with a known URL, 0.32 GB compressed. Mayo Clinic Arizona's file is **21.5 GB**, so the downloader skips files over 5 GB until there is a streaming parser.
- **Parsing:** all 72 files read (target was 90%): 59 with service-code prices, 13 that bill only by revenue code (psychiatric hospitals and the four Exceptional Community Hospitals). New handling added for this: formats detected from content rather than file names (many URLs have none), zip files, a fallback reader for a CSV polars rejected (Kingman Regional, line breaks inside values), and a per-file outcome log (`data/parsed/parse_report.csv`, not in Git).
- **Output:** 11,820,817 prices in 39 MB of Parquet. Only Pima County is loaded into Postgres for now (see open items).

## Compliance

Nine rules per hospital ([`ingest/hospitals/compliance.py`](../ingest/hospitals/compliance.py)), scored by dbt in `marts.hospital_compliance_scores`. Highlights:

- **No insurer prices at all:** the three Carondelet hospitals (St. Joseph's, St. Mary's, Holy Cross) and the four Exceptional Community Hospitals.
- **Mostly percentages or formulas, not dollars:** six hospitals, as low as 3% in dollars (White Mountain Regional).
- **CMS's own validator** (`@cmsgov/hpt-validator-cli` 1.10.8) agreed on five spot-checked files. It checks format, not substance: it passes a file with no insurer prices. It also corrected one of our findings: CMS accepts M/D/YYYY dates in CSV files.

## Insurer names

Statewide files use 820 insurer names. `dim_payer_plans` maps each payer + plan to a parent company (exact alias, else an ordered pattern) and a market (from patterns on payer and plan text, so a "Work Comp" plan under a commercial payer counts as workers' comp). Coverage: parent company for 90% of price rows, market for 80%. A dbt unit test pins the precedence rules.

## Orchestration

[`orchestration/definitions.py`](../orchestration/definitions.py) defines the pipeline as Dagster assets:

```
hospital list -> price-file sources -> [per hospital] download -> parse -> load
                                       payer names, compliance checks -> dbt models
```

- One partition per hospital, so a bad file fails only its own run.
- A Redis lock per hospital prevents two runs downloading the same file (tested by holding the lock by hand).
- Asset checks flag a row count moving more than 30% between runs and a file older than a year.
- A failure sensor posts to `ALERT_WEBHOOK_URL` when one is set.
- Weekly schedules (Mondays, Arizona time): discovery at 6:00, one run per hospital at 7:00, warehouse build at 11:00.

```
$env:DAGSTER_HOME = "$PWD\.dagster_home"
uv run dagster dev -m orchestration.definitions
```

## Open items

- **Load all of Arizona into Postgres?** About 11.8M rows, an estimated 4-8 GB more disk (the machine has about 20 GB free). Controlled by `LOAD_COUNTIES`.
- **Copy 10 blocked `cms-hpt.txt` files by hand** (Abrazo x4, Northern Arizona Healthcare x2, Valleywise, Onvida, Arizona Spine & Joint, City of Hope), as was done for Carondelet.
- **Alerts:** where should failures go (Slack webhook, email)?
- **Mayo Clinic Arizona** needs a streaming parser (Phase 4 skill).
- **Insurer names:** the last 20% of price rows have no market yet; needs a review pass.
- **Scope:** the CMS list has no rehabilitation or long-term acute care hospitals.
