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
