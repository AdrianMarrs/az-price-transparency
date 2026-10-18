"""Write every payer and plan name in the hospitals' prices to raw.payer_plans (in the lake).

Usage:
    uv run python -m ingest.hospitals.payer_plans

dbt's dim_payer_plans maps each (payer, plan) to a parent company and a market. Building it
from this small table keeps that mapping's input small. Reads raw.hospital_charges in the
lake (every hospital written there, any state) and writes raw/payer_plans/payer_plans.parquet,
replaced each run; with no prices yet it is empty.
"""

import polars as pl

from ingest import lake

SCHEMA = {"ccn": pl.String, "payer_name": pl.String, "plan_name": pl.String, "rows": pl.Int64}


def payer_plan_counts() -> pl.DataFrame:
    df = lake.read(
        "raw/hospital_charges/*/*/*.parquet",
        sql="""
        SELECT ccn, payer_name, plan_name, count(*) AS rows FROM {}
        WHERE payer_name IS NOT NULL
        GROUP BY ccn, payer_name, plan_name ORDER BY ccn, payer_name, plan_name""",
    )
    return pl.DataFrame(schema=SCHEMA) if df.is_empty() else df.cast(SCHEMA)


def main() -> None:
    df = payer_plan_counts()
    lake.replace_folder("raw/payer_plans", df, "payer_plans.parquet")
    print(f"{df.height:,} hospital x payer x plan rows, "
          f"{df.select('payer_name', 'plan_name').n_unique():,} distinct payer-plans")  # fmt: skip


if __name__ == "__main__":
    main()
