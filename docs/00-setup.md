# 00 · Setup

Phase 0 gives the project a reproducible local stack, automated checks on every push, and a cloud account that cannot run up a bill.

## Stack and why

| Piece | Choice | Why | Considered instead |
| --- | --- | --- | --- |
| Language | Python 3.12 | The data ecosystem (polars, dbt, Dagster, ijson) lives here | C#: my strongest language, but a weaker fit for data tooling |
| Environments | uv | One fast tool for Python versions, virtual environments and a lockfile | pip + venv, Poetry |
| Dataframes | polars | Fast, low-memory, and handles unpivoting wide price files cleanly | pandas |
| Validation | pydantic | Typed models with clear error messages for rejected rows | Hand-written checks |
| Warehouse | PostgreSQL 16 | System of record; widely used; dbt support is mature | DuckDB: simpler locally, may still be used for exploration |
| Raw storage | Compressed files (local disk now, S3 later) | Hospitals overwrite their files, so every download is kept as evidence; files are cheaper and simpler than any database for this | MongoDB: cut, since DynamoDB already covers NoSQL in Phase 3 and Postgres `jsonb` covers nested JSON |
| Locks and cache | Redis 7 (local) | Locks so two scheduled runs never fetch the same file; cache-aside for slow warehouse queries | ElastiCache in front of the API: not on the Free plan, needs a VPC, and DynamoDB is already fast. CloudFront caches the API instead |
| Local services | Docker Compose | One command brings up Postgres and Redis, the same on any machine | Installing each database natively |
| CI | GitHub Actions | Lint, format check and tests on every push and pull request | None needed beyond this yet |
| Lint and format | ruff | One fast tool for both | flake8 + black |
| Cloud | AWS, Free plan | Matches my Lambda background; the Free plan makes charges impossible while learning | Paid plan with budget alerts (alerts don't stop spending) |

## Decisions worth noting

- **No long-lived AWS keys.** The CLI signs in with `aws login`, which issues short-lived credentials through the browser. CI will use GitHub OIDC in Phase 3 for the same reason.
- **Free plan over budget alerts.** A budget alert only sends email; on the Free plan the account simply cannot be billed. The trade-off is a 6-month limit and a restricted service list, which is acceptable until Phase 3.
- **LF line endings.** `.gitattributes` forces LF so files behave the same in Windows, Linux containers and CI.
- **Data never enters Git.** `data/` is ignored; raw downloads go to local disk now and S3 later.

## Running it

```
docker compose up -d      # Postgres :5432, Redis :6379
uv sync                   # install dependencies
uv run pytest             # tests
uv run ruff check .       # lint
```

Postgres: user `pt`, password `pt`, database `prices` (local development only).
