"""Write every payer and plan name in the parsed files to raw.payer_plans.

Usage:
    uv run python -m ingest.hospitals.payer_plans

dbt's dim_payer_plans maps each (payer, plan) to a parent company and a market. Building
it from this small table means the mapping covers every parsed hospital, whether or not
its prices have been loaded into Postgres. With no parsed files the table is left empty.
"""

import os
from pathlib import Path

import polars as pl
import psycopg

PARSED_DIR = Path("data/parsed")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://pt:pt@localhost:5432/prices")


def payer_plan_counts(parsed_dir: Path = PARSED_DIR) -> pl.DataFrame:
    if not list(parsed_dir.glob("*.parquet")):
        return pl.DataFrame(schema={"ccn": pl.String, "payer_name": pl.String,
                                    "plan_name": pl.String, "rows": pl.UInt32})  # fmt: skip
    return (
        pl.scan_parquet(parsed_dir / "*.parquet")
        .filter(pl.col("payer_name").is_not_null())
        .group_by("ccn", "payer_name", "plan_name")
        .agg(pl.len().alias("rows"))
        .sort("ccn", "payer_name", "plan_name")
        .collect()
    )


def main() -> None:
    df = payer_plan_counts()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.transaction():
        conn.execute("CREATE SCHEMA IF NOT EXISTS raw")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS raw.payer_plans (
                   ccn text NOT NULL, payer_name text NOT NULL, plan_name text,
                   rows bigint NOT NULL)"""
        )
        conn.execute("TRUNCATE raw.payer_plans")
        with conn.cursor().copy(
            "COPY raw.payer_plans (ccn, payer_name, plan_name, rows) FROM STDIN"
        ) as copy:
            for row in df.iter_rows():
                copy.write_row(row)
    print(f"{df.height:,} hospital x payer x plan rows, "
          f"{df.select('payer_name', 'plan_name').n_unique():,} distinct payer-plans")  # fmt: skip


if __name__ == "__main__":
    main()
