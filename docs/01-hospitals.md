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

## Shoppable services found (parser, 2026-10-16)

Measured against CMS's 70 specified shoppable services (74 codes, `warehouse/seeds/shoppable_services.csv`).

| CCN | Hospital | Services found | Valid prices | Duplicates dropped | Rejected |
| --- | --- | ---: | ---: | ---: | ---: |
| 030006 | Tucson Medical Center | 70 | 3,858 | 67 | 0 |
| 030085 | Northwest Medical Center | 52 | 4,642 | 3,224 | 0 |
| 030064 | Banner UMC Tucson | 50 | 4,601 | 1,736 | 0 |
| 030114 | Oro Valley Hospital | 50 | 4,812 | 3,454 | 0 |
| 030148 | Northwest Sahuarita | 50 | 3,381 | 2,344 | 62 |
| 030111 | Banner UMC South | 45 | 4,017 | 544 | 0 |
| 030010 | St. Mary's | 35 | 198 (list and cash only) | 0 | 0 |
| 030011 | St. Joseph's | 32 | 194 (list and cash only) | 0 | 0 |
| 034033 | El Dorado Springs | 5 | 350 | 0 | 0 |
| 034022 | Sonora Behavioral Health | 0 | 0 | 0 | 0 |
| 034030 | Palo Verde Behavioral Health | 0 | 0 | 0 | 0 |

- **The two psychiatric hospitals match none of the 70**: they bill by revenue code (per-diem room and board) and drug code, and the CMS list is CPT- and DRG-based. A lookup site needs a separate view for behavioral health.
- **Sahuarita's rejects are a data error in the file**: the plan "NODE Devoted Health MCR ADV" has a blank payer name in its column header, so its negotiated prices cannot be attributed.
- **Duplicates** are chargemaster lines that differ only by the hospital's internal item number (CDM); once that is dropped they are identical in every price-relevant field.

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
