"""Write every payer and plan name in the parsed files to raw.payer_plans (in the lake).

Usage:
    uv run python -m ingest.hospitals.payer_plans

dbt's dim_payer_plans maps each (payer, plan) to a parent company and a market. Building
it from this small table means the mapping covers every parsed hospital, whether or not
its prices have been loaded. Written to raw/payer_plans/payer_plans.parquet, replaced each
run; with no parsed files it is empty.
"""

from pathlib import Path

import polars as pl

from ingest import lake

PARSED_DIR = Path("data/parsed")


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
    df = payer_plan_counts().with_columns(pl.col("rows").cast(pl.Int64))
    lake.replace_folder("raw/payer_plans", df, "payer_plans.parquet")
    print(f"{df.height:,} hospital x payer x plan rows, "
          f"{df.select('payer_name', 'plan_name').n_unique():,} distinct payer-plans")  # fmt: skip


if __name__ == "__main__":
    main()
