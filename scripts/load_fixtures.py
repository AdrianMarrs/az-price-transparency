"""Parse the test fixtures and load them into raw.hospital_charges.

Usage:
    uv run python scripts/load_fixtures.py

CI uses this so `dbt build` runs its models and tests on real (small) data from every
hospital, without downloading anything. Locally it would replace the full data for those
hospitals, so it refuses to run unless CI is set.
"""

import os
import sys
from pathlib import Path

import polars as pl
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest.hospitals.load import (
    DATABASE_URL,
    HOSPITALS_PATH,
    create_table,
    load_hospital,
)
from ingest.hospitals.parse import load_shoppable, parse_file

FIXTURES = Path("tests/fixtures")


def main() -> None:
    if not os.environ.get("CI"):
        sys.exit("Refusing to overwrite local data; set CI=1 to run anyway.")
    states = dict(pl.read_csv(HOSPITALS_PATH, infer_schema_length=0).select("ccn", "state").rows())
    shoppable = load_shoppable()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        create_table(conn)
        for path in sorted(FIXTURES.glob("*.*")):
            ccn = path.stem
            _, valid, _ = parse_file(path, shoppable)
            df = valid.with_columns(
                pl.lit(ccn).alias("ccn"),
                pl.lit(states[ccn]).alias("state"),
                pl.lit(None, pl.Int64).alias("source_file_id"),
            )
            load_hospital(conn, df, ccn, states[ccn])
            print(f"{ccn}  {df.height:>5} rows")


if __name__ == "__main__":
    main()
