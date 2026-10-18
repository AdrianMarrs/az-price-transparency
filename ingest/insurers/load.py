"""Write normalized insurer rates to the Parquet lake, as raw.insurer_rates.

Usage:
    uv run python -m ingest.insurers.load [--insurer cigna] --month 2026-10 [--from-bucket]

Reads data/insurers/parquet/insurer=<name>/month=<m>/*.parquet (written by
ingest.insurers.normalize, or by the monthly cloud run: --from-bucket downloads that month
from the data bucket first) into the lake (ingest/lake.py) as
raw/insurer_rates/insurer=<name>/month=<m>/network=<network>/data.parquet. Each network's
folder is replaced whole, so a reload never leaves half a network behind.
"""

import argparse
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from ingest import lake
from ingest.insurers.normalize import PARQUET_DIR, SCHEMA
from ingest.storage import download_dir

COLUMNS = list(SCHEMA)
FOLDER = "raw/insurer_rates"
KEYS = ("insurer", "month", "network")  # the folder names, not columns in the file
NAME = re.compile(r"[A-Za-z0-9._-]+")


def load_network(df: pl.DataFrame) -> int:
    """Replace the rows for df's insurer, month and network. Returns rows written."""
    if df.is_empty():
        return 0
    keys = df.select(*KEYS).unique()
    if keys.height != 1:
        raise ValueError(f"expected one insurer/month/network, got {keys.height}")
    values = keys.row(0)
    if not all(NAME.fullmatch(v or "") for v in values):
        raise ValueError(f"not a plain name: {values}")
    rel = "/".join(f"{k}={v}" for k, v in zip(KEYS, values, strict=True))
    rows = df.select(c for c in COLUMNS if c not in KEYS).with_columns(
        pl.lit(datetime.now(UTC)).dt.cast_time_unit("us").alias("loaded_at")
    )
    lake.replace_folder(f"{FOLDER}/{rel}", rows)
    return df.height


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--insurer", default="cigna")
    parser.add_argument("--month", required=True)
    parser.add_argument(
        "--from-bucket", action="store_true", help="download from DATA_BUCKET first"
    )
    args = parser.parse_args()
    src = PARQUET_DIR / f"insurer={args.insurer}" / f"month={args.month}"
    if args.from_bucket:
        print(f"downloaded {len(download_dir(src))} files to {src}")
    paths = sorted(Path(src).glob("*.parquet"))
    if not paths:
        raise SystemExit(f"no Parquet files in {src}")
    total = empty = 0
    for path in paths:
        started = time.perf_counter()
        rows = load_network(pl.read_parquet(path))
        total += rows
        if rows:
            print(f"{path.stem:<50} {rows:>10,} rows  {time.perf_counter() - started:5.1f}s")
        else:
            empty += 1
    print(f"{total:,} rows from {len(paths) - empty} networks ({empty} with no Arizona hospitals)")


if __name__ == "__main__":
    main()
