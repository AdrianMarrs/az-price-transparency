# The hospital pipeline (ingest.pipeline) for ECS Fargate Spot, Linux/x86-64: Fargate Spot
# doesn't run ARM64 tasks. Build from the repo root:
#   uv run python scripts/push_image.py pipeline <repository URL>
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    BROWSER_CHANNEL=chromium \
    DUCKDB_PATH=/app/data/warehouse.duckdb

WORKDIR /app

# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

# Chromium and its system libraries, for files that refuse programs (ingest/hospitals/
# browser.py). There's no display, so only the headless try runs.
RUN playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*

COPY ingest ingest
COPY serving serving
COPY warehouse warehouse

# Runs as an unprivileged user; it writes only under /app/data and dbt's own folders.
RUN useradd --create-home runner \
    && mkdir -p data warehouse/target warehouse/logs \
    && chown -R runner data warehouse/target warehouse/logs
USER runner
# DuckDB's extensions, so a run doesn't download them.
RUN python -c "import duckdb; [duckdb.sql(f'INSTALL {e}') for e in ('httpfs', 'aws', 'json')]"

ENTRYPOINT ["python", "-m", "ingest.pipeline"]
