# 01 · Hospital price files

The 11 in-scope Pima County hospitals publish 11 files in three shapes, all claiming CMS template version 3.0.0. Two hospitals (St. Joseph's and St. Mary's) publish no insurer prices at all, and the files disagree on column order, date formats and header spelling, so the parser must read columns by name and normalize everything.

Downloaded 2026-10-16. Numbers come from `scripts/profile_raw_files.py`.

## The files

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

**TMC's 17% is mostly not missing data.** 1,606,470 of its rows (83%) give no dollar amount and the algorithm "Service is bundled into MS-DRG payment where appropriate" with methodology `other`: the item is paid as part of the inpatient stay's single DRG case rate. The parser needs a separate category for "bundled" so the quality score does not count these as missing.

## Compliance findings

1. **St. Joseph's and St. Mary's publish no payer-specific negotiated charges** and no de-identified minimum or maximum, only gross and discounted cash prices. Both are required by 45 CFR 180.50(b). Automated access to their `cms-hpt.txt` is also blocked by a bot challenge.
2. **Banner serves `cms-hpt.txt` only to browser user agents**, though its price files download normally.
3. **Dates not in the template's `YYYY-MM-DD` format:** Sonora (`12/31/2025`), El Dorado Springs (`7/31/2026`); the three Northwest Healthcare files pad the date with leading spaces.
4. **El Dorado Springs lists only 23 items**, and 43% of its payer prices have no dollar amount.
5. **Sonora's file is mostly drugs:** 7,964 of 8,792 rows carry only an NDC code, and only 1,726 payer prices exist across its 130 payer-plans.

## What the parser keeps (2026-10-16)

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

All 11 files parse in about 13 seconds; the output is 6 MB of Parquet.

- **The two psychiatric hospitals have no service codes at all**: they bill by revenue code (per-diem room and board) and drug code. A lookup site needs a separate view for behavioral health.
- **Sahuarita's rejects are a data error in the file**: the plan "NODE Devoted Health MCR ADV" has a blank payer name in its column header, so its negotiated prices cannot be attributed.
- **Duplicates** are chargemaster lines that differ only by the hospital's internal item number (CDM); once that is dropped they are identical in every price-relevant field. In the Northwest files they are about a third of all rows.

## Loading into Postgres (2026-10-16)

`ingest/hospitals/load.py` replaces each hospital's rows in `raw.hospital_charges` (partitioned by state; all 11 hospitals are in `raw.hospital_charges_az`) in one transaction: `DELETE` by CCN, then `COPY`.

| Method, 50,000 rows into an empty table | Rows per second | vs. COPY |
| --- | ---: | ---: |
| `COPY ... FROM STDIN (FORMAT csv)` | 586,468 | |
| `executemany` (psycopg batches in pipeline mode) | 36,461 | 16x slower |
| One `INSERT` per row, each committed | 1,823 | 322x slower |

- **Full load:** 1,609,202 rows; steady-state COPY into the real table is about 200,000 rows/s (Banner Tucson's 369,274 rows in 1.7-1.9 s).
- **Size in Postgres:** 529 MB (337 bytes per row) plus a 34 MB index, against 6 MB of Parquet for the same rows.
- **Reloads needed two fixes.** Without an index on `ccn`, each hospital's `DELETE` scanned the whole partition (47 s for one hospital). And at the default `max_wal_size` of 1GB, a full reload triggered back-to-back checkpoints of 45-58 s each; local Postgres now runs with 4GB. Deleted rows also stay on disk until vacuumed (the table reached 1.5 GB after two reloads).
- **Still open:** occasional 10-25 s stalls on Docker Desktop for Windows, waiting on WAL writes, while raw disk throughput measures 3.4-4.2 GB/s. To compare against RDS in Phase 3.

## Quirks the parser must handle (each becomes a test case)

- **Column order differs** between files (Banner puts `modifiers` after `plan_name`; El Dorado puts `standard_charge|min`/`max` at the end). Read columns by name, never by position.
- **Blank trailing headers** in row 1 (Northwest files, Sonora, El Dorado). Ignore empty column names.
- **Spaces inside headers** (Sonora: `description `, `code |1`, `standard_charge | gross`). Strip spaces before matching.
- **Payer and plan wrapped in labels** (Sonora: `[payer_AETNA ]|[plan_ HMO/PPO]`). Strip the `[payer_`/`[plan_` wrappers and spaces.
- **Numbered duplicate plans** (El Dorado: `AETNACPD`, `AETNACPD_1`, `AETNACPD_2`). Keep them separate; flag for the payer-alias seed.
- **A malformed metadata row** (El Dorado: an unquoted comma in the attester field shifts row 2 by one column). Read metadata by header name and tolerate extra fields.
- **Line breaks inside values** (Palo Verde: `hospital_name` ends in `\r\n`). Strip all text.
- **Inconsistent case** (Palo Verde: `Inpatient`, `Per diem`). Lowercase `setting` and `methodology`.
- **Multi-value cells** separated by `|` or ` | ` (`type_2_npi` in Northwest files, `location_name` and `hospital_address` in Banner Tucson).
- **Different numbers of code columns**: one (Sonora) to five (Northwest). Code types include internal `CDM` and revenue codes `RC`; shoppable services match on `CPT`, `HCPCS` and `MS-DRG` only.
- **Legal-entity names differ from hospital names** (Carondelet files say "SMSJ Tucson Holdings LLC"). Identify hospitals by CCN from our seed, not by the file's name field.
