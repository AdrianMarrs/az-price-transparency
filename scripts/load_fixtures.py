"""Parse the test fixtures and load them into raw.hospital_charges and raw.insurer_rates.

Usage:
    uv run python scripts/load_fixtures.py

CI uses this so `dbt build` runs its models and tests on real (small) data from every
hospital, without downloading anything. The insurer fixture goes through the same parser,
normalizer and loader as a real Transparency in Coverage file. Locally it would replace the full data for those
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
from ingest.insurers import load as insurer_load
from ingest.insurers.normalize import normalize_file
from ingest.insurers.tic import hospital_npis, output_path, run_file

FIXTURES = Path("tests/fixtures")
INSURER_FIXTURES = FIXTURES / "insurers"
FIXTURE_MONTH = "2026-10"


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
        insurer_load.create_table(conn)
        npis = hospital_npis()
        for path in sorted(INSURER_FIXTURES.glob("*.json.gz")):
            run_file(str(path), "fixture", FIXTURE_MONTH, npis)
            raw = output_path("fixture", FIXTURE_MONTH, str(path))
            rows = insurer_load.load_network(conn, normalize_file(raw, "fixture", FIXTURE_MONTH))
            print(f"{path.name}  {rows:>5} insurer rows")


if __name__ == "__main__":
    main()
