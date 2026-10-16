# Arizona Price Transparency

A free, open, auditable price lookup for Pima County, Arizona: named hospitals, insurer-specific prices where they exist, and a data-quality score that explains every missing or percentage-only price.

Behind it is a data pipeline that collects the prices hospitals and health insurers are required to publish, validates and normalizes them, and adds an AI query layer.

**Status:** Phases 1-2 (hospital data, local). All 95 in-scope Arizona hospitals checked; 82 price files parsed into 14.6M prices, all loaded into Postgres; weekly pipeline in Dagster. Cloud (Phase 3) not started.

## Findings so far

- **39 of 95 Arizona hospitals pass every price transparency rule we can check**; 68 publish usable insurer prices. [Compliance report](docs/reports/arizona-compliance-2026-10-16.md)
- **Eight hospitals publish no insurer prices at all**, and 13 block programs (bot challenges or refused access) from reading `cms-hpt.txt`, the file meant to point programs to their prices. Three of them block the price file itself too.
- **The insurer market matters more than the hospital.** In Pima County, a knee MRI's median insurer price runs from $167 (Medicaid) to $1,080 (commercial). [Details](docs/01-hospitals.md)

## Running it

```
docker compose up -d                                   # Postgres, Redis
uv sync
uv run pytest
uv run dbt build --project-dir warehouse --profiles-dir warehouse
$env:DAGSTER_HOME = "$PWD\.dagster_home"               # PowerShell
uv run dagster dev -m orchestration.definitions        # pipeline UI at localhost:3000
```

Design notes, one per phase: [setup](docs/00-setup.md), [hospital files](docs/01-hospitals.md), [every Arizona hospital](docs/02-arizona.md), [cloud](docs/03-cloud.md).

## What it does

- Downloads hospital price files (CMS Hospital Price Transparency rule) and insurer rate files (Transparency in Coverage rule)
- Validates each hospital file against the CMS template and scores compliance
- Streams insurer files too large to store, keeping only Arizona providers
- Normalizes everything into a Postgres warehouse with dbt
- Serves fast lookups from DynamoDB through a Lambda API, with a React site and an MCP server for Claude

## Layout

```
ingest/hospitals/   find, download, parse, load and check hospital price files
orchestration/      Dagster assets, schedules and checks
warehouse/          dbt project (seeds, staging, marts, analyses)
scripts/            one-off tools: profiling, test fixtures, compliance report
docs/               design notes, one per phase; reports/
tests/              pytest, with real-row fixtures from every file format
```

Planned: `infra/` (Terraform), `api/` (Lambda), `web/` (React), `mcp/` (MCP server), `ingest/insurers/`.

## Stack

Python, Postgres, dbt, Dagster, DynamoDB, Redis, Docker, Terraform, GitHub Actions, AWS Lambda and S3, React, MCP.

## License

MIT
