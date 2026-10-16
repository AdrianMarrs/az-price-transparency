"""Load parsed hospital prices into Postgres with COPY.

Usage:
    uv run python -m ingest.hospitals.load [--ccn 030006 ...] [--compare]

Reads data/parsed/<ccn>.parquet and loads it into raw.hospital_charges, a table
partitioned by state (one partition per state, created on first use). Each hospital is
replaced in one transaction, so a reload never leaves half a hospital behind.

--compare also times plain row-by-row INSERTs on a sample, for the COPY speedup.
"""

import argparse
import io
import os
import re
import time
from pathlib import Path

import polars as pl
import psycopg
from psycopg import sql

PARSED_DIR = Path("data/parsed")
HOSPITALS_PATH = Path("warehouse/seeds/hospitals.csv")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://pt:pt@localhost:5432/prices")

COLUMNS = [
    "state", "ccn", "source_file_id", "description", "code", "code_type", "cms_shoppable_id",
    "setting", "billing_class", "modifiers", "payer_name", "plan_name", "methodology",
    "price_type", "amount", "algorithm",
]  # fmt: skip

TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.hospital_charges (
    state            text          NOT NULL,
    ccn              text          NOT NULL,
    source_file_id   bigint,        -- raw.source_files.id: which download this came from
    description      text          NOT NULL,
    code             text          NOT NULL,
    code_type        text          NOT NULL,  -- CPT/HCPCS or MS-DRG
    cms_shoppable_id int,                     -- one of CMS's 70 shoppable services
    setting          text          NOT NULL,  -- inpatient, outpatient, both
    billing_class    text,
    modifiers        text,
    payer_name       text,
    plan_name        text,
    methodology      text,
    price_type       text          NOT NULL,
    amount           numeric(18,4),
    algorithm        text,
    loaded_at        timestamptz   NOT NULL DEFAULT now()
) PARTITION BY LIST (state);
-- Reloading a hospital deletes its rows first; without this the DELETE scans the whole
-- state partition (47 s instead of under 2 s for one hospital at 1.6M rows).
CREATE INDEX IF NOT EXISTS hospital_charges_ccn_idx ON {schema}.hospital_charges (ccn);
"""


def create_table(conn: psycopg.Connection, schema: str = "raw") -> None:
    conn.execute(sql.SQL(TABLE_SQL).format(schema=sql.Identifier(schema)))


def ensure_partition(conn: psycopg.Connection, state: str, schema: str = "raw") -> None:
    if not re.fullmatch(r"[A-Z]{2}", state):
        raise ValueError(f"not a state code: {state!r}")
    conn.execute(
        sql.SQL(
            "CREATE TABLE IF NOT EXISTS {part} PARTITION OF {parent} FOR VALUES IN ({state})"
        ).format(
            part=sql.Identifier(schema, f"hospital_charges_{state.lower()}"),
            parent=sql.Identifier(schema, "hospital_charges"),
            state=sql.Literal(state),
        )
    )


def as_csv(df: pl.DataFrame) -> bytes:
    """The frame in COPY's CSV format: no header, nulls as unquoted empty fields."""
    buffer = io.BytesIO()
    df.select(COLUMNS).write_csv(buffer, include_header=False, null_value="")
    return buffer.getvalue()


def copy_rows(conn: psycopg.Connection, table: sql.Composable, df: pl.DataFrame) -> None:
    columns = sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
    with conn.cursor().copy(
        sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv)").format(table, columns)
    ) as copy:
        copy.write(as_csv(df))


def load_hospital(
    conn: psycopg.Connection, df: pl.DataFrame, ccn: str, state: str, schema: str = "raw"
) -> tuple[float, float]:
    """Replace one hospital's rows with df (which must have COLUMNS).

    Returns (seconds deleting the old rows, seconds copying the new ones)."""
    table = sql.Identifier(schema, "hospital_charges")
    with conn.transaction():
        ensure_partition(conn, state, schema)
        started = time.perf_counter()
        conn.execute(
            sql.SQL("DELETE FROM {} WHERE state = %s AND ccn = %s").format(table), (state, ccn)
        )
        deleted = time.perf_counter()
        copy_rows(conn, table, df)
        copied = time.perf_counter()
    return deleted - started, copied - deleted


def compare_load_methods(conn: psycopg.Connection, df: pl.DataFrame) -> dict[str, float]:
    """Rows per second for three ways to load the same rows into an empty scratch table:
    COPY, executemany (psycopg batches it in pipeline mode), and one INSERT per row
    committed separately (the naive loop)."""
    insert = sql.SQL("INSERT INTO load_test ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, COLUMNS)),
        sql.SQL(", ").join(sql.Placeholder() * len(COLUMNS)),
    )
    sizes = {"COPY": 50_000, "executemany": 50_000, "one INSERT per row": 2_000}
    rates = {}
    for method, n in sizes.items():
        sample = df.select(COLUMNS).head(n)
        conn.execute("CREATE TEMP TABLE load_test (LIKE raw.hospital_charges INCLUDING DEFAULTS)")
        started = time.perf_counter()
        if method == "COPY":
            copy_rows(conn, sql.Identifier("load_test"), sample)
        elif method == "executemany":
            with conn.transaction(), conn.cursor() as cur:
                cur.executemany(insert, sample.rows())
        else:
            for row in sample.rows():  # autocommit: each INSERT is its own transaction
                conn.execute(insert, row)
        rates[method] = sample.height / (time.perf_counter() - started)
        conn.execute("DROP TABLE load_test")
    return rates


def source_file_id(conn: psycopg.Connection, path: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM raw.source_files WHERE path = %s AND outcome = 'downloaded' "
        "ORDER BY id DESC LIMIT 1",
        (path,),
    ).fetchone()
    return row[0] if row else None


def load_parsed(conn: psycopg.Connection, ccn: str, state: str) -> pl.DataFrame:
    """Load data/parsed/<ccn>.parquet into the warehouse; returns the rows loaded (an empty
    file still replaces the hospital's old rows, so stale prices don't linger)."""
    df = pl.read_parquet(PARSED_DIR / f"{ccn}.parquet")
    source_id = source_file_id(conn, df["source_path"][0]) if df.height else None
    df = df.with_columns(
        pl.lit(state).alias("state"), pl.lit(source_id, pl.Int64).alias("source_file_id")
    )
    delete_s, copy_s = load_hospital(conn, df, ccn, state)
    rate = f"{df.height / copy_s:>9,.0f} rows/s" if df.height else ""
    print(f"{ccn}  {df.height:>9,} rows  delete {delete_s:5.2f}s  copy {copy_s:5.2f}s  {rate}")
    return df


def state_of(ccn: str) -> str:
    states = pl.read_csv(HOSPITALS_PATH, infer_schema_length=0).select("ccn", "state")
    return dict(states.rows())[ccn]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ccn", nargs="*", help="only these hospitals")
    parser.add_argument("--compare", action="store_true", help="also time row-by-row INSERTs")
    args = parser.parse_args()

    states = dict(pl.read_csv(HOSPITALS_PATH, infer_schema_length=0).select("ccn", "state").rows())
    paths = sorted(PARSED_DIR.glob("*.parquet"))
    if args.ccn:
        paths = [p for p in paths if p.stem in args.ccn]

    total_rows = 0
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        create_table(conn)
        biggest = None
        for path in paths:
            df = load_parsed(conn, path.stem, states[path.stem])
            total_rows += df.height
            if biggest is None or df.height > biggest.height:
                biggest = df
        conn.execute("ANALYZE raw.hospital_charges")
        print(f"total {total_rows:,} rows")
        if args.compare and biggest is not None:
            rates = compare_load_methods(conn, biggest)
            for method, rate in rates.items():
                print(f"{method:>20}: {rate:>9,.0f} rows/s  "
                      f"({rates['COPY'] / rate:,.0f}x slower than COPY)")  # fmt: skip


if __name__ == "__main__":
    main()
