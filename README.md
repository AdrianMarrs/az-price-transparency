# Clear Healthcare Prices

A free, open, auditable price lookup for U.S. hospitals: cash prices, list prices and the rates each insurer has agreed to, from the files hospitals are required to publish, with a data-quality score that explains every missing or percentage-only price.

Behind it is a data pipeline that finds, downloads, validates and normalizes the prices hospitals and health insurers are required to publish.

**Status:** Live at [clearhealthcareprices.com](https://clearhealthcareprices.com) for every state. 5,222 non-federal hospitals in the 50 states, DC and Puerto Rico each have a page and a compliance score; 1,350 of them publish a price file the pipeline can read. Arizona was built first and goes deepest: all 95 in-scope hospitals checked by hand, 82 price files parsed into 14.6M prices, plus Cigna's insurer rates for Arizona providers. The raw data is a Parquet lake, the warehouse a DuckDB file built by dbt, and the site's data static JSON files behind CloudFront, all in Terraform. Refresh schedules exist but are turned off, so the data is the October 2026 pass.

## Findings so far

- **About a quarter of U.S. hospitals publish a price file a program can find and read** (1,350 of 5,222). For most of the rest, no website is on record to start from; 12 refuse even a browser on a home connection. [Details](docs/05-national.md)
- **15 of 95 Arizona hospitals pass every price transparency rule we can check** (39 before the cash and list price rules were added); 68 publish usable insurer prices. [Compliance report](docs/reports/arizona-compliance-2026-10-16.md) (from before those two rules)
- **Eight Arizona hospitals publish no insurer prices at all**, and 13 block programs (bot challenges or refused access) from reading `cms-hpt.txt`, the file meant to point programs to their prices. Three of them block the price file itself too.
- **The insurer market matters more than the hospital.** In Pima County, a knee MRI's median insurer price runs from $167 (Medicaid) to $1,080 (commercial). [Details](docs/01-hospitals.md)

## How it's served

Every answer the site needs is precomputed as a gzip-compressed JSON file (per state: one per service, one per hospital, and a search list) next to the site in S3, served by CloudFront. The React site pre-renders a page for every state, hospital and featured service. There is no API or database to run; for Arizona the measured cost was well under $1 a month. [Details](docs/03-cloud.md#static-data-files), [the website](docs/06-website.md)

## Running it

```
docker compose up -d redis                             # Dagster's per-hospital locks
uv sync
uv run pytest
uv run dbt build --project-dir warehouse --profiles-dir warehouse
$env:DAGSTER_HOME = "$PWD\.dagster_home"               # PowerShell
uv run dagster dev -m orchestration.definitions        # pipeline UI at localhost:3000
docker compose up web                                  # the site at localhost:5173, live reload (data from the live site; see web/.env.example)
cd web; npm ci; npm run dev                            # the same without Docker
```

Design notes, one per phase: [setup](docs/00-setup.md), [hospital files](docs/01-hospitals.md), [every Arizona hospital](docs/02-arizona.md), [cloud](docs/03-cloud.md), [insurer files](docs/04-insurer.md), [every state](docs/05-national.md), [the website](docs/06-website.md).

## What it does

- Finds each hospital's price file: by hand for Arizona, automatically for every other state (CMS's hospital list, hospital websites, and each site's `cms-hpt.txt`)
- Downloads hospital price files (CMS Hospital Price Transparency rule) and insurer rate files (Transparency in Coverage rule)
- Validates each hospital file against the CMS template and scores compliance
- Streams insurer files too large to store, keeping only the providers needed (Cigna, Arizona so far)
- Keeps the parsed rows as a Parquet lake and builds a DuckDB warehouse from it with dbt
- Exports each state's data as static files, served with a React site by CloudFront

## Layout

```
ingest/hospitals/   find, download, parse, load and check hospital price files
ingest/insurers/    stream insurer rate files, keeping only the state's hospitals
ingest/national/    find every US hospital's price file
ingest/lake.py      the Parquet lake the warehouse is built from
orchestration/      Dagster assets, schedules (all off) and checks
warehouse/          dbt project on DuckDB (seeds, staging, marts, serving)
serving/            export the site's data as static JSON files
infra/              Terraform
web/                the React site
scripts/            one-off tools: profiling, test fixtures, compliance report
docs/               design notes, one per phase; reports/
tests/              pytest, with real-row fixtures from every file format
```

The repository keeps its first name, `az-price-transparency`, from when it covered Arizona only.

## Stack

Python, polars, DuckDB, Parquet, dbt, Dagster, Redis, Docker, Terraform, GitHub Actions, AWS (S3, CloudFront, ECS Fargate for the insurer run), React.

## License

MIT
