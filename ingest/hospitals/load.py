"""Write parsed hospital prices to the Parquet lake, as raw.hospital_charges.

Usage:
    uv run python -m ingest.hospitals.load [--ccn 030006 ...]

Reads data/parsed/<ccn>.parquet and writes it to the lake (ingest/lake.py) as
raw/hospital_charges/state=<ST>/ccn=<ccn>/data.parquet. The folder is replaced whole, so a
reload never leaves half a hospital behind, and an empty file still clears a hospital's old
prices. state and ccn are the folder names, not columns in the file.
"""

import argparse
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from ingest import lake
from ingest.hospitals import source_log

PARSED_DIR = Path("data/parsed")
HOSPITALS_PATH = Path("warehouse/seeds/hospitals.csv")
FOLDER = "raw/hospital_charges"

SCHEMA = {
    "source_file_id": pl.Int64,  # raw.source_files.id: which download this came from
    "description": pl.String,
    "code": pl.String,
    "code_type": pl.String,  # CPT/HCPCS or MS-DRG
    "cms_shoppable_id": pl.Int32,  # one of CMS's 70 shoppable services
    "setting": pl.String,  # inpatient, outpatient, both
    "billing_class": pl.String,
    "modifiers": pl.String,
    "payer_name": pl.String,
    "plan_name": pl.String,
    "methodology": pl.String,
    "price_type": pl.String,
    "amount": pl.Decimal(18, 4),
    "algorithm": pl.String,
}
COLUMNS = list(SCHEMA)


def folder(ccn: str, state: str) -> str:
    """The hospital's folder in the lake; refuses anything that isn't a plain name, since
    both become part of a path."""
    if not re.fullmatch(r"[A-Z]{2}", state):
        raise ValueError(f"not a state code: {state!r}")
    if not re.fullmatch(r"[0-9A-Z]{6}", ccn):
        raise ValueError(f"not a CCN: {ccn!r}")
    return f"{FOLDER}/state={state}/ccn={ccn}"


def write_hospital(df: pl.DataFrame, ccn: str, state: str) -> str:
    """Replace one hospital's prices with df (which must have COLUMNS); returns the file."""
    rows = df.select(pl.col(c).cast(t) for c, t in SCHEMA.items()).with_columns(
        pl.lit(datetime.now(UTC)).dt.cast_time_unit("us").alias("loaded_at")
    )
    return lake.replace_folder(folder(ccn, state), rows)


def load_parsed(ccn: str, state: str, attempts: pl.DataFrame | None = None) -> pl.DataFrame:
    """Write data/parsed/<ccn>.parquet to the lake; returns the rows written."""
    df = pl.read_parquet(PARSED_DIR / f"{ccn}.parquet")
    if attempts is None:
        attempts = source_log.read()
    source_id = source_log.downloaded_id(attempts, df["source_path"][0]) if df.height else None
    df = df.with_columns(pl.lit(source_id, pl.Int64).alias("source_file_id"))
    started = time.perf_counter()
    write_hospital(df, ccn, state)
    print(f"{ccn}  {df.height:>9,} rows  {time.perf_counter() - started:5.2f}s")
    return df


def state_of(ccn: str) -> str:
    states = pl.read_csv(HOSPITALS_PATH, infer_schema_length=0).select("ccn", "state")
    return dict(states.rows())[ccn]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ccn", nargs="*", help="only these hospitals")
    args = parser.parse_args()

    states = dict(pl.read_csv(HOSPITALS_PATH, infer_schema_length=0).select("ccn", "state").rows())
    paths = sorted(PARSED_DIR.glob("*.parquet"))
    if args.ccn:
        paths = [p for p in paths if p.stem in args.ccn]
    attempts = source_log.read()
    total = sum(load_parsed(p.stem, states[p.stem], attempts).height for p in paths)
    print(f"total {total:,} rows under {lake.path(FOLDER)}")


if __name__ == "__main__":
    main()
