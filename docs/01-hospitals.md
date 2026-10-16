# 01 · Hospital price files

Phase 1 turned the price files of Pima County's 11 in-scope hospitals into 1,609,202 validated prices in Postgres, modeled with dbt, and answered "what does a knee MRI cost, by insurer?" with one query checked by hand against the raw files. Along the way the files showed why this needs engineering: three formats, inconsistent spelling and dates, two hospitals with no insurer prices at all, and one hospital whose price file can't be fetched by a program.

Data downloaded 2026-10-16.

## The pipeline

| Step | Code | Output |
| --- | --- | --- |
| 1. List hospitals | `ingest/hospitals/hospital_list.py` | `warehouse/seeds/hospitals.csv`: 13 Pima hospitals from CMS, 2 federally run (flagged), 11 in scope |
| 2. Find each price file | `ingest/hospitals/find_sources.py` | `warehouse/seeds/hospital_sources.csv`, via each site's `cms-hpt.txt` |
| 3. Download | `ingest/hospitals/download.py` | `data/raw/<date>/*.gz` (2.2 GB as 107 MB gzip), every attempt in `raw.source_files` |
| 4. Parse and validate | `ingest/hospitals/parse.py` | `data/parsed/<ccn>.parquet` (6 MB) and `<ccn>_rejects.csv` |
| 5. Load | `ingest/hospitals/load.py` | `raw.hospital_charges`, partitioned by state |
| 6. Model | `warehouse/` (dbt) | `marts.fct_prices`, three dimensions, `marts.price_summary` |
| 7. Answer | `warehouse/analyses/knee_mri.sql` | Price per hospital and insurer plan |

```
uv run python -m ingest.hospitals.find_sources
uv run python -m ingest.hospitals.download
uv run python -m ingest.hospitals.parse
uv run python -m ingest.hospitals.load
uv run dbt build --project-dir warehouse --profiles-dir warehouse
```

## The files

All 11 claim CMS template version 3.0.0. Counts from `scripts/profile_raw_files.py`.

| CCN | Hospital | Shape | Date in file | Rows | Payer-plans | Payer prices | In dollars |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 030006 | Tucson Medical Center | CSV tall | 2026-04-30 | 1,940,458 | 16 | 1,940,458 | 17% (see below) |
| 030010 | St. Mary's (Carondelet) | JSON | 2026-04-06 | 10,307 | 0 | 0 | none |
| 030011 | St. Joseph's (Carondelet) | JSON | 2026-04-06 | 10,401 | 0 | 0 | none |
| 030064 | Banner UMC Tucson | CSV tall | 2026-09-25 | 561,223 | 62 | 560,983 | 99% |
| 030085 | Northwest Medical Center | CSV wide | `    2026-04-01` | 46,483 | 62 | 1,026,316 | 99% |
| 030111 | Banner UMC South | CSV tall | 2026-10-13 | 395,217 | 56 | 394,987 | 99% |
| 030114 | Oro Valley Hospital | CSV wide | `    2026-04-01` | 42,177 | 67 | 1,021,702 | 99% |
| 030148 | Northwest Sahuarita | CSV wide | `    2026-04-01` | 41,939 | 47 | 618,483 | 100% |
| 034022 | Sonora Behavioral Health | CSV wide | `12/31/2025` | 8,792 | 130 | 1,726 | 100% |
| 034030 | Palo Verde Behavioral Health | CSV tall | 2026-08-31 | 293 | 31 | 293 | 100% |
| 034033 | El Dorado Springs | CSV wide | `7/31/2026` | 23 | 124 | 511 | 57% |

- **Tall** CSV: one row per item × payer × plan, with `payer_name` and `plan_name` columns.
- **Wide** CSV: one row per item, with a group of columns per payer and plan, e.g. `standard_charge|Aetna|Aetna ALL|negotiated_dollar`. Wide files run from 444 to 1,183 columns.
- **JSON**: a list of items, each with `code_information` and `standard_charges`. Payer prices would sit in `payers_information`, but neither Carondelet file has any.

**TMC's 17% is mostly not missing data.** 1,606,470 of its rows (83%) give no dollar amount and the algorithm "Service is bundled into MS-DRG payment where appropriate": the item is paid as part of the inpatient stay's single DRG case rate. The parser keeps these as `negotiated_algorithm` prices and dbt flags them `is_bundled`, so a quality score won't count them as missing.

## Compliance findings

1. **St. Joseph's and St. Mary's publish no payer-specific negotiated charges** and no de-identified minimum or maximum, only gross and discounted cash prices. Both are required by 45 CFR 180.50(b).
2. **Carondelet blocks automated access to its `cms-hpt.txt`** with a Cloudflare bot challenge, though CMS intends the file for automated discovery. It was copied by hand from a browser (`ingest/hospitals/manual_cms_hpt/`); the block is still recorded as `found_manual_copy`.
3. **Banner serves `cms-hpt.txt` only to browser user agents**; its price files download normally. Recorded as `found_browser_ua_only`.
4. **Dates not in the template's `YYYY-MM-DD` format:** Sonora (`12/31/2025`), El Dorado Springs (`7/31/2026`); the three Northwest Healthcare files pad the date with leading spaces.
5. **El Dorado Springs lists only 23 items**, and 43% of its payer prices have no dollar amount.
6. **Sonora's file is mostly drugs:** 7,964 of 8,792 rows carry only an NDC code, and only 1,726 payer prices exist across its 130 payer-plans.
7. **Sahuarita's file has a plan with no payer name** ("NODE Devoted Health MCR ADV" under a blank payer in its header), so 3,057 of its prices can't be attributed and are rejected.

## Problems hit and how the parser handles each

Each is covered by a test on real rows (`tests/fixtures/`, about 50 rows per hospital file, cut by `scripts/make_fixtures.py` and kept byte-exact via `.gitattributes`).

| Problem | Example | Handling |
| --- | --- | --- |
| Three shapes | tall CSV, wide CSV, JSON | Each is read into one item table, then expanded to one row per price |
| Column order differs | Banner puts `modifiers` after `plan_name`; El Dorado puts `min`/`max` last | Columns are read by name, never position |
| Spaces inside headers | Sonora: `description `, `code |1`, `standard_charge | gross` | Headers are normalized before matching |
| Payer and plan wrapped in labels | Sonora: `[payer_AETNA ]|[plan_ HMO/PPO]` | Wrappers and spaces stripped; payer case kept |
| Blank trailing headers | Row 1 of the Northwest files, Sonora, El Dorado | Empty column names ignored |
| Malformed metadata row | El Dorado: an unquoted comma in the attester field shifts row 2 | Metadata read by header name; extra fields tolerated |
| Date formats | `    2026-04-01`, `7/31/2026`, `12/31/2025` | Trimmed and parsed as ISO or US dates |
| Line breaks inside values | Palo Verde: hospital name ends in `\r\n` | All whitespace collapsed |
| Inconsistent case | Palo Verde: `Inpatient`, `Per diem` | `setting`, `methodology`, `billing_class` lowercased |
| One to five code columns | Sonora has one, Northwest five; types include internal `CDM` and revenue codes `RC` | Every code column checked; matching uses CPT, HCPCS and MS-DRG only |
| Code type spelling | `CPT`, `hcpcs`, `MS-DRG`, `MS DRG`; DRG `8` vs `008` | Normalized; DRGs zero-padded to three digits |
| Numbered duplicate plans | El Dorado: `AETNACPD`, `AETNACPD_1`, `AETNACPD_2` | Kept separate (a question for the payer seed) |
| Exact duplicates | Chargemaster lines differing only by internal item number | Dropped and counted: 436,648 rows, a third of the Northwest files |
| Legal-entity names | Carondelet files say "SMSJ Tucson Holdings LLC" | Hospitals identified by CCN from our seed, never by the file's name field |
| Bad values | Blank payer, negative or non-numeric amount, unknown setting | Row rejected to `<ccn>_rejects.csv` with the reason |

**Validation runs in bulk.** Polars expressions check whole columns (about 13 seconds for all 11 files); a pydantic model states the same rules readably, and a test checks that both accept exactly the same rows in every fixture.

## What the parser keeps

**Decision: keep every service code, flag the CMS 70.** Filtering to CMS's 70 specified shoppable services (74 codes) kept only 26,115 prices, 0.75% of the usable data, and left out common services such as a knee MRI with contrast (73722), knee replacement as outpatient surgery (27447) and screening colonoscopy (G0121). Keeping every CPT, HCPCS and MS-DRG code would keep 3.5M prices, but 45% of those are supplies and devices and another 8% drugs and miscellaneous codes, which nobody shops for on their own.

So the parser keeps **services people get**: CPT codes (procedures, tests, imaging, visits), HCPCS G codes and MS-DRGs (inpatient stays), and flags the 70 in `cms_shoppable_id`. Supplies (HCPCS A, C, E, K, L), drugs (J), miscellaneous codes and hospital-internal codes are dropped.

| CCN | Hospital | Codes | Of CMS's 70 | Valid prices | Duplicates dropped | Rejected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 030064 | Banner UMC Tucson | 4,934 | 50 | 369,274 | 84,477 | 0 |
| 030006 | Tucson Medical Center | 10,754 | 70 | 298,789 | 5,130 | 0 |
| 030111 | Banner UMC South | 3,417 | 45 | 265,609 | 36,263 | 0 |
| 030085 | Northwest Medical Center | 3,389 | 52 | 262,425 | 111,188 | 0 |
| 030114 | Oro Valley Hospital | 2,943 | 50 | 246,541 | 119,550 | 0 |
| 030148 | Northwest Sahuarita | 2,573 | 50 | 155,176 | 80,040 | 3,057 |
| 030011 | St. Joseph's | 1,502 | 32 | 5,592 (list and cash only) | 0 | 0 |
| 030010 | St. Mary's | 1,445 | 35 | 5,440 (list and cash only) | 0 | 0 |
| 034033 | El Dorado Springs | 11 | 5 | 356 | 0 | 0 |
| 034022 | Sonora Behavioral Health | 0 | 0 | 0 | 0 | 0 |
| 034030 | Palo Verde Behavioral Health | 0 | 0 | 0 | 0 | 0 |
| | **Total** | | | **1,609,202** | **436,648** | **3,057** |

**The two psychiatric hospitals have no service codes at all**: they bill per day by revenue code and by drug code. A lookup site needs a separate view for behavioral health.

## Loading into Postgres

`ingest/hospitals/load.py` replaces each hospital's rows in `raw.hospital_charges` (partitioned by state; all 11 hospitals are in `raw.hospital_charges_az`) in one transaction: `DELETE` by CCN, then `COPY`.

| Method, 50,000 rows into an empty table | Rows per second | vs. COPY |
| --- | ---: | ---: |
| `COPY ... FROM STDIN (FORMAT csv)` | 586,468 | |
| `executemany` (psycopg batches in pipeline mode) | 36,461 | 16x slower |
| One `INSERT` per row, each committed | 1,823 | 322x slower |

- **Full load:** 1,609,202 rows; steady-state COPY into the real table is about 200,000 rows/s (Banner Tucson's 369,274 rows in 1.7-1.9 s).
- **Size:** 529 MB in Postgres (337 bytes per row) plus a 34 MB index, against 6 MB of Parquet for the same rows.
- **Reloads needed two fixes.** Without an index on `ccn`, each hospital's `DELETE` scanned the whole partition (47 s for one hospital). And at the default `max_wal_size` of 1GB, a full reload triggered back-to-back checkpoints of 45-58 s each; local Postgres now runs with 4GB. Deleted rows also stay on disk until vacuumed (the table reached 1.5 GB after two reloads).
- **Still open:** occasional 10-25 s stalls on Docker Desktop for Windows, waiting on WAL writes, while raw disk throughput measures 3.4-4.2 GB/s. To compare against RDS in Phase 3.

## Modeling with dbt

| Model | Rows | Grain |
| --- | ---: | --- |
| `staging.stg_hospital_charges` (view) | 1,609,202 | One price, with a row key, a service key and an `is_bundled` flag |
| `marts.dim_hospitals` | 13 | One hospital, with its price-file status |
| `marts.dim_payers` | 148 | One payer name, mapped to a parent company and a market by `seeds/payer_aliases.csv` |
| `marts.dim_services` | 10,760 | One service code, with its most common description |
| `marts.fct_prices` | 1,609,202 | One price |
| `marts.price_summary` | 324,918 | Count, sum, mean, min, quartiles and max per state (or US) × service × setting × billing class × price type × market |

- **National rows come from individual prices**, never from state rows: medians can't be combined, and averaging state averages would over-weight small states.
- **29 dbt tests** check keys, accepted values and relationships; one warns when a payer name isn't in the alias seed. CI loads the fixtures into a Postgres service container and runs `dbt build` on every push.
- **The market matters more than the hospital.** For a knee MRI at the outpatient facility rate, the Arizona median is $167 for Medicaid, $265 for Medicare Advantage, $420 for marketplace plans, $1,080 for commercial and $8,485 for rented provider networks.

## Answering the question: a knee MRI

`warehouse/analyses/knee_mri.sql` answers "what does a knee MRI without contrast (CPT 73721) cost at each Pima County hospital, by insurer?" for the outpatient facility charge. It returns 169 insurer-plan prices across 6 hospitals and 18 insurer groups; St. Joseph's and St. Mary's publish no insurer prices, and the psychiatric hospitals don't do MRIs.

- **Cash can beat insurance.** Banner's cash price is $586 (South) to $686 (Tucson), while Cigna's negotiated rate there is $1,328 and BCBS AZ commercial is $950.
- **One system, one contract.** The three Northwest Healthcare hospitals have identical insurer rates but different cash prices ($1,745 at Sahuarita, $2,327 at the other two).
- **One knee or both.** Northwest lists both knees (`MR-LW JOINT WO BI`) at exactly twice one knee; TMC charges insurers $358.31 either way. The query keeps the range rather than picking one line.
- **Checked by hand** against the raw files, without the parser: TMC Cigna $358.31 and cash $1,451.24; Oro Valley BCBS PimaConnect $601.01 / $1,202.01 and cash $2,327.28; Banner South Cigna $1,328.00 and cash $585.55. All match.

## Open items

- **Market must come from payer and plan.** The alias seed assigns a market per payer name, but plan names carry it too: "BCBS AZ Work Comp" is counted as commercial, and payers mapped `mixed` have plans named "Medicaid", "Medicare Advantage" and "ACA Health Plan".
- **The payer seed is a first pass** from public knowledge of who owns which plan; `unknown` and `mixed` rows need checking.
- **One line or both:** comparisons should separate single and bilateral line items rather than show a range.
