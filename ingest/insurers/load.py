"""Load normalized insurer rates into Postgres with COPY.

Usage:
    uv run python -m ingest.insurers.load [--insurer cigna] --month 2026-10

Reads data/insurers/parquet/insurer=<name>/month=<m>/*.parquet (written by
ingest.insurers.normalize) into raw.insurer_rates. Each network is replaced in one
transaction, so a reload never leaves half a network behind.
"""

import argparse
import io
import time
from pathlib import Path

import polars as pl
import psycopg
from psycopg import sql

from ingest.hospitals.load import DATABASE_URL
from ingest.insurers.normalize import PARQUET_DIR, SCHEMA

COLUMNS = list(SCHEMA)

TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.insurer_rates (
    insurer                 text      NOT NULL,
    network                 text      NOT NULL,
    month                   text      NOT NULL,  -- the file's month, e.g. 2026-10
    ccn                     text      NOT NULL,
    billing_code_type       text,
    billing_code            text      NOT NULL,
    description             text,
    negotiation_arrangement text,                -- ffs, bundle, capitation
    negotiated_type         text,                -- negotiated, fee schedule, percentage, ...
    negotiated_rate         double precision,
    billing_class           text,                -- professional, institutional
    setting                 text,                -- inpatient, outpatient, both
    service_codes           text,                -- place-of-service codes, comma-separated
    modifiers               text,
    expiration_date         text,
    loaded_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS insurer_rates_file_idx
    ON {schema}.insurer_rates (insurer, month, network);
"""


def create_table(conn: psycopg.Connection, schema: str = "raw") -> None:
    conn.execute(sql.SQL(TABLE_SQL).format(schema=sql.Identifier(schema)))


def load_network(conn: psycopg.Connection, df: pl.DataFrame, schema: str = "raw") -> int:
    """Replace the rows for df's insurer, month and network. Returns rows copied."""
    if df.is_empty():
        return 0
    keys = df.select("insurer", "month", "network").unique()
    if keys.height != 1:
        raise ValueError(f"expected one insurer/month/network, got {keys.height}")
    insurer, month, network = keys.row(0)
    table = sql.Identifier(schema, "insurer_rates")
    buffer = io.BytesIO()
    df.select(COLUMNS).write_csv(buffer, include_header=False, null_value="")
    with conn.transaction():
        conn.execute(
            sql.SQL("DELETE FROM {} WHERE insurer = %s AND month = %s AND network = %s").format(
                table
            ),
            (insurer, month, network),
        )
        columns = sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
        with conn.cursor().copy(
            sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv)").format(table, columns)
        ) as copy:
            copy.write(buffer.getvalue())
    return df.height


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--insurer", default="cigna")
    parser.add_argument("--month", required=True)
    args = parser.parse_args()
    src = PARQUET_DIR / f"insurer={args.insurer}" / f"month={args.month}"
    paths = sorted(Path(src).glob("*.parquet"))
    if not paths:
        raise SystemExit(f"no Parquet files in {src}")
    with psycopg.connect(DATABASE_URL) as conn:
        create_table(conn)
        for path in paths:
            started = time.perf_counter()
            rows = load_network(conn, pl.read_parquet(path))
            print(f"{path.stem:<45} {rows:>10,} rows  {time.perf_counter() - started:5.1f}s")


if __name__ == "__main__":
    main()
