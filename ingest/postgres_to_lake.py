"""One-time copy of the Postgres raw tables into the Parquet lake (ingest/lake.py), so the
DuckDB warehouse can be built from exactly what the Postgres one was, and the two compared.

Usage:
    uv run python -m ingest.postgres_to_lake

Uses DuckDB's postgres extension (downloaded on first use). Writes under LAKE (data/lake):
hospital_charges one file per hospital, insurer_rates one per insurer x month x network,
and the small tables one file each.
"""

import os
import time

import duckdb

from ingest import lake

DSN = "host=localhost port=5432 dbname=prices user=pt password=pt"


def main() -> None:
    con = duckdb.connect()
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(f"ATTACH '{DSN}' AS pg (TYPE postgres, READ_ONLY)")
    root = lake.root()
    started = time.time()

    def copy(query: str, dest: str, partition: list[str] | None = None) -> None:
        t = time.time()
        target = lake.path(dest)
        os.makedirs(target if partition else os.path.dirname(target), exist_ok=True)
        options = "FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 500000"
        if partition:
            options += f", PARTITION_BY ({', '.join(partition)}), OVERWRITE_OR_IGNORE"
        con.execute(f"COPY ({query}) TO '{target}' ({options})")
        print(f"{dest:40} {time.time() - t:6.0f}s")

    copy("SELECT * FROM pg.raw.hospital_charges",
         "raw/hospital_charges", ["state", "ccn"])  # fmt: skip
    copy("SELECT * FROM pg.raw.insurer_rates",
         "raw/insurer_rates", ["insurer", "month", "network"])  # fmt: skip
    copy("SELECT * FROM pg.raw.source_files", "raw/source_files/postgres.parquet")
    copy("SELECT * FROM pg.raw.compliance_checks", "raw/compliance_checks/checks.parquet")
    copy("SELECT * FROM pg.raw.payer_plans", "raw/payer_plans/payer_plans.parquet")
    print(f"done in {time.time() - started:.0f}s under {root}")


if __name__ == "__main__":
    main()
