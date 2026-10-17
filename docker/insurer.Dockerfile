# The monthly insurer run (ingest.insurers.run) for ECS Fargate, Linux/ARM64.
# Build from the repo root: scripts/push_image.py builds, tags and pushes it to ECR.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY ingest ingest
COPY warehouse/seeds/hospital_npis.csv warehouse/seeds/hospital_npis.csv

# Runs as an unprivileged user; it only writes its working files under /app/data.
RUN useradd --create-home runner && mkdir data && chown runner data
USER runner

ENTRYPOINT ["python", "-m", "ingest.insurers.run"]
