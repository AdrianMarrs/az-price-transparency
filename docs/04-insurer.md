# 04 · One insurer's Arizona rates

Hospitals publish what they charge; insurers publish what they've agreed to pay, under the Transparency in Coverage rule. Phase 4 reads one insurer's files and keeps the rates for Arizona hospitals, so the two sides can be compared.

## Which insurer: Cigna

Among the insurers in Arizona hospitals' own price files, these have contracts with the most hospitals (commercial, Medicare Advantage and marketplace plans):

| Insurer | Arizona hospitals | Hospital price rows |
| --- | ---: | ---: |
| UnitedHealthcare | 58 | 1.22M |
| Cigna | 57 | 0.94M |
| Aetna | 57 | 0.77M |
| Humana | 55 | 0.70M |
| Blue Cross Blue Shield of Arizona | 51 | 0.94M |

Cigna was chosen for how its files are published:

- **One table of contents for the whole company** (`cigna-health-life-insurance-company_index.json`, 57 MB, refreshed monthly). UnitedHealthcare publishes a separate index per employer group, tens of thousands of them.
- **Hosted on S3** behind CloudFront (`Server: AmazonS3`), so a cloud run sits next to the data.
- **A manageable size:** 25,843 plans share just **124 distinct in-network rate files, 29.7 GB compressed in total** (measured with a HEAD request per file, October 2026).
- **Arizona-specific networks:** Arizona HMO (30 MB), Phoenix AZ Connect (40 MB) and three AZ LocalFlex variants (1.7 GB each), plus national networks that also include Arizona providers.

## The file format

Each in-network file is one gzipped JSON document (they compress about 22x: 30 MB becomes 671 MB):

```
{ "reporting_entity_name", "last_updated_on", "version",
  "provider_references": [ { "provider_group_id": 1006779,
                             "provider_groups": [ { "npi": [...], "tin": {...} } ] } ],
  "in_network": [ { "billing_code": "73721", "billing_code_type": "CPT",
                    "negotiated_rates": [ { "provider_references": [1006779, ...],
                                            "negotiated_prices": [ { "negotiated_type",
                                              "negotiated_rate", "setting", "billing_class",
                                              "service_code", "expiration_date" } ] } ] } ] }
```

Rates point back to provider groups by ID. Cigna's files keep the groups in the same file (none in separate files), and list them before the rates.

## The streaming parser (`ingest/insurers/tic.py`)

httpx streams the download, zlib decompresses it in pieces of at most 256 KB, and ijson's C backend parses whole objects from the stream. Nothing but the kept rates is written.

- **Pass 1** reads `provider_references` and keeps the groups that contain an Arizona hospital's own NPI (237 NPIs for 83 hospitals, `role = hospital` in `hospital_npis.csv`; co-located practices are excluded). When the references come first, the stream is cut at the top-level `"in_network"` key and closed off, so pass 1 downloads only the start of the file.
- **Pass 2** reads `in_network` and keeps each billing code's rates that reference a kept group, tagged with the hospitals' CCNs.
- A file that lists its references last is read whole twice.

**What made it fast.** On the 30 MB Arizona HMO file:

| Approach | Time |
| --- | ---: |
| Python code for every JSON event | 68 s |
| ijson push mode (C backend, objects fed through coroutines) | 31 s |
| ijson pull mode (entirely in C) | **14.7 s** |
| The same, with `tracemalloc` on to measure memory | 447 s |

`tracemalloc` hooks every allocation, so memory is measured instead by sampling the process's working set every 5 seconds, which costs nothing.

**Tests** use tiny hand-made files that follow the schema, read in 7-byte chunks so chunk boundaries fall everywhere. They caught two real bugs: closing the first parser early raised "premature EOF", and a key split across two chunks went unseen.

## Measured runs (October 2026)

| Network | Compressed | Time | Rate | Pass 1 read | Groups kept | Codes kept | Working set (start → max) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Arizona HMO | 30 MB | 15 s | 2.1 MB/s | — | 36 of 591 | 16,817 of 17,674 | +14 MB |
| Phoenix AZ Connect | 40 MB | 21 s | 1.9 MB/s | 1 MB | 42 of 1,453 | 28,608 of 178,523 | 190 → 207 MB |
| AZ LocalFlex (excl. EBH and Pathwell) | 1.73 GB | 14.9 min | 1.9 MB/s | 16 MB | 32 of 54,488 | 32,340 of 1,553,848 | 214 → 227 MB |

**Memory is flat:** on the 1.7 GB file (about 38 GB of JSON), the working set peaked at 225 MB in the first quarter of the run and 227 MB in the last. Throughput is the same on a 30 MB and a 1.7 GB file; parsing, not the download (18 MB/s here), is the limit. At about 2 MB/s, all 124 Cigna files (29.7 GB) would take about 4 hours on one core; files are independent, so a cloud run can process them in parallel.

## Landing the data

- **Raw:** kept records as JSON Lines, one line per billing code, gzip-compressed: `raw/insurer=cigna/month=2026-10/` in the data bucket (and `data/insurers/raw/` locally). 1–2 MB per network.
- **Parquet** (`ingest/insurers/normalize.py`): one row per hospital × negotiated price, duplicates removed: `parquet/insurer=cigna/month=2026-10/`.

| Network | Rows | Hospitals |
| --- | ---: | ---: |
| Arizona HMO | 309,871 | 48 |
| AZ LocalFlex (excl. EBH and Pathwell) | 255,397 | 45 |
| Phoenix AZ Connect | 106,458 | 45 |

Almost all are `fee schedule` dollar amounts; about 2% are percentages and a few are per diem.

**Watch the billing class when comparing.** Many of a hospital's insurer rates are *professional* (for example, the radiologist's read of a knee MRI, $45–$96), while hospital price files mostly list the facility charge. A comparison has to match professional with professional and institutional with institutional.

## In the warehouse

`ingest/insurers/load.py` copies each network's Parquet into `raw.insurer_rates` with COPY, replacing that insurer, month and network in one transaction (671,726 rows; 1.8–13.5 s per network).

`stg_insurer_rates` translates the insurer files' terms into the hospital files' terms:

| Transparency in Coverage | Hospital files / `fct_prices` |
| --- | --- |
| `CPT`, `HCPCS` (separate) | `CPT/HCPCS` (combined) |
| `institutional` | `facility` |
| `fee schedule`, `per diem` | the same methodology |
| `percentage` | `negotiated_percentage`, methodology "percent of total billed charges" |
| `negotiated`, `derived` | methodology "other" |

`fct_prices` now has a `source` column: `hospital` or `insurer`. For insurer rows, `payer_name` is the insurer (`Cigna`) and `plan_name` is the network. Only codes that some hospital also prices are kept: 10,519 of Cigna's 15,808 CPT, HCPCS and MS-DRG codes, or 434,956 rows. Revenue codes, APCs, ICD and custom codes stay in staging.

The serving models (the DynamoDB items and `price_summary`) read hospital rows only, so adding insurer data changed nothing on the site: the items' content hashes and `price_summary` were checked identical before and after.

**A first look, before matching plans properly.** Matching each hospital's own Cigna price to Cigna's published rate for the same hospital, code, setting and billing class (medians on both sides) gives 64,970 pairs at 32 hospitals. Cigna's number is 20% higher at the median; only 8.7% agree within 1%, and 26% differ by more than 2x. Hospital files label plans loosely ("Commercial", "All Commercial Plans") while Cigna's are specific networks, so part of this is comparing different contracts.

**Disk space.** dbt rebuilds a table by writing a full new copy before dropping the old one, so rebuilding `fct_prices` (4.2 GB) briefly needs twice its size. On a nearly full laptop that filled the disk mid-build. Postgres recovered cleanly from its write-ahead log on restart.

## The monthly cloud run

`ingest/insurers/run.py` runs every in-network file in Cigna's table of contents, in a container on ECS Fargate (`infra/main/insurer_run.tf`, image from `docker/insurer.Dockerfile`).

- **Finding the files.** Cigna's index URL is signed and expires after about a month, so it can't be stored. Cigna publishes a small pointer, `cigna.com/static/mrf/latest.json`, with the current signed URL and its reporting month; the run starts there. (Cigna also publishes per-state indexes, but only for Colorado.)
- **Parallel.** One worker process per vCPU, each streaming one file at a time. 4 vCPU, 8 GB, ARM64 (Graviton, about 20% cheaper than x86).
- **Resumable.** Each file's status is an item in DynamoDB (`az-price-transparency-runs`): queued, done with its stats, or failed with the error. A rerun for the same month skips done files, so a failure costs only the files that failed. Each run adds a `SUMMARY#<start>` item.
- **Scheduled** by EventBridge Scheduler at 06:00 UTC on the 5th of each month. If the insurer hasn't posted the new month yet, the pointer still names last month, every file is already done, and the run exits within a minute.
- **Guardrails.** A 4-hour timeout on the container (a run takes about one), least-privilege roles (the task can write only `raw/insurer=*`, `parquet/insurer=*` and its status table), outbound-only networking in the default VPC (no NAT gateway, which would cost about $32 a month), and $20 and $50 monthly budget alerts for the account.

### The first run (October 2026)

| | |
| --- | --- |
| Files | 124 (29.7 GB compressed) |
| Wall time | 61 minutes on 4 vCPU; 3.7 hours of parsing in total |
| Parse rate | 2.0–2.8 MB/s per worker, the same as the laptop |
| Estimated cost | $0.16 (vCPU and memory hours at Fargate's ARM price) |
| Kept | 4,851,647 rates in 23 networks; 101 networks have no Arizona hospital |

**Nine files failed, and a resume fixed them in 3½ minutes.** All nine raised "incorrect header check", meaning they weren't gzip as the parser assumed:

- Five `.json.gz` files are *also* served with `Content-Encoding: gzip`, so httpx removed the gzip layer before the parser saw it. Downloads are now read raw.
- Four partner files (Sagamore, Upper Midwest, Priority Health) are `.zip` archives of one JSON file. The parser now inflates the first entry straight after its local header, so it streams like gzip and never needs the archive's directory at the end.

The format now comes from the file's first bytes, not its name, and a stream that stops early raises instead of being read as a complete file. The resume skipped the 115 finished files and ran only the nine.

**National networks carry most of the Arizona data.** National PPO and OAP each cover 76 Arizona hospitals, more than the Arizona-specific networks (Arizona HMO: 48). Many networks carry identical rate sets (seven networks have exactly 303,013 rows, four have 304,444): the same national contract sold under different names. Counting distinct prices means deduplicating across networks.

**Inline provider groups.** The schema lets a rate list its providers inline instead of by reference to `provider_references`; the parser originally skipped those without noticing. It now matches them and counts them per file (`inline_group_rates`). None of the nine files rerun with the new code use them; the November run will count all 124.

**Cost per run** comes from Cost Explorer, which lags by up to a day: `scripts/run_cost.py --month 2026-10` writes the ECS charge for the run days next to the estimate.

### Loading

`uv run python -m ingest.insurers.load --month 2026-10 --from-bucket` downloads the month's Parquet (124 files, 23 MB) and loads it: 4,851,647 rows into `raw.insurer_rates`.

In the warehouse: 3,098,950 of those rows reach `fct_prices` (the codes some hospital also prices), covering 55 hospitals; 326,615 are distinct once the same contract repeated across networks is counted once. Cigna has rates for 76 Arizona hospitals in all. The other 21 are mostly behavioral health hospitals (Haven, Oasis, Quail Run, Palo Verde) and small rural ones (Page, Copper Queen, Cobre Valley): Cigna pays them per day by revenue code, or a percentage of billed charges (`CSTM-ALL`, "all services"), not per procedure. Those rates stay in `stg_insurer_rates`; there's no CPT or DRG price at the hospital to compare them with. The site's data is unchanged (the export's dry run would write nothing).

### Rerun with the better NPI list

Coverage (`insurer_hospital_coverage`) showed six hospitals that list Cigna in their own files but had no hospital NPI to match, so the NPI lookup was improved (street directions ignored, then a name search in the same city): 256 hospital NPIs for 93 hospitals, up from 237 for 83. Each file's status records a fingerprint of the NPI list it was parsed with (`npis_version`), so the next run redid all 124.

**The first rerun hung for its whole 4-hour limit**, with no file finished (about $0.63 wasted). Computing the fingerprint read the NPI list with polars in the parent process, and on Linux the workers are forked: a child forked after polars has started its thread pool can deadlock in it. The tests use threads and Windows spawns processes, so neither caught it. Workers are now spawned, and a test checks the start method.

| | First run | Rerun |
| --- | --- | --- |
| Wall time | 61 minutes | 44 minutes |
| Estimated cost | $0.16 | $0.12 |
| Rates kept | 4,851,647 | 5,681,292 |
| Hospitals with Cigna rates | 76 | 83 |
| Rows in `fct_prices` | 3,098,950 at 55 hospitals | 3,668,861 at 61 hospitals |

**Coverage per hospital**, comparing the insurer's files with the hospital's own:

| | Before | After |
| --- | --- | --- |
| In both | 51 | 56 |
| Cigna's files only | 25 | 27 |
| Hospital's file only | 6 | 1 |
| Neither | 13 | 11 |

The one left, Kingman Regional, lists Cigna and has two hospital NPIs, but neither appears in Cigna's files. The eleven in neither are the Exceptional Community micro-hospitals, behavioral health and state hospitals, and tribal facilities (Sage Memorial, Tuba City).

**Outliers:** 11,487 rates (0.2%) are flagged against their peers: 7,954 over ten times the peer median and 3,533 under a tenth. They stay in `fct_prices` with a `rate_flag`; impossible rates (zero, negative, over 100%) are kept out.
