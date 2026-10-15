# Arizona Price Transparency

A data pipeline that collects the prices Arizona hospitals and health insurers are required to publish, validates and normalizes them, and serves a searchable price lookup with an AI query layer.

**Status:** Phase 0, setup. Work in progress.

## What it does

- Downloads hospital price files (CMS Hospital Price Transparency rule) and insurer rate files (Transparency in Coverage rule)
- Validates each hospital file against the CMS template and scores compliance
- Streams insurer files too large to store, keeping only Arizona providers
- Normalizes everything into a Postgres warehouse with dbt
- Serves fast lookups from DynamoDB through a Lambda API, with a React site and an MCP server for Claude

## Layout

```
ingest/        Python loaders (hospitals/, insurers/)
warehouse/     dbt project
infra/         Terraform
api/           Lambda API
web/           React site
mcp/           MCP server
docs/          design docs, one per phase
tests/
```

## Stack

Python, Postgres, dbt, Dagster, DynamoDB, Redis, Docker, Terraform, GitHub Actions, AWS Lambda and S3, React, MCP.

## License

MIT
