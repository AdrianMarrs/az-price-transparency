"""The Parquet lake: the raw tables the warehouse is built from, as files.

LAKE is a folder (data/lake, the default) or an S3 prefix (s3://bucket/lake) in the cloud.
dbt-duckdb reads it directly (warehouse/models/staging/_sources.yml), so nothing is loaded
into a database first. Layout:

    raw/hospital_charges/state=AZ/ccn=030006/*.parquet   one hospital's parsed prices
    raw/insurer_rates/insurer=cigna/month=2026-10/network=.../*.parquet
    raw/source_files/<run>.parquet                       download attempts, one file a run
    raw/compliance_checks/checks.parquet                 hospital x rule, rewritten each run
    raw/payer_plans/payer_plans.parquet                  payer and plan names per hospital

A hospital or network is replaced by rewriting its folder, so a rerun never leaves half
of one behind.
"""

import os
import shutil
from pathlib import Path

import duckdb
import polars as pl

DEFAULT = "data/lake"


def root() -> str:
    return os.environ.get("LAKE", DEFAULT).rstrip("/")


def is_s3() -> bool:
    return root().startswith("s3://")


def path(rel: str) -> str:
    return f"{root()}/{rel.lstrip('/')}"


def connect() -> duckdb.DuckDBPyConnection:
    """A DuckDB connection that can read and write the lake (S3 credentials from the
    usual AWS chain when LAKE is on S3)."""
    con = duckdb.connect()
    if is_s3():
        con.execute("INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;")
        con.execute("CREATE SECRET lake (TYPE s3, PROVIDER credential_chain)")
    return con


def replace_folder(rel: str, df: pl.DataFrame, name: str = "data.parquet") -> str:
    """Make the folder rel hold exactly this frame (one file); returns its path."""
    target = path(f"{rel}/{name}")
    if is_s3():
        con = connect()
        con.register("frame", df.to_arrow())
        delete_prefix(rel)
        con.execute(f"COPY frame TO '{target}' (FORMAT parquet, COMPRESSION zstd)")
        return target
    folder = Path(path(rel))
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    df.write_parquet(target, compression="zstd")
    return target


def append(rel: str, df: pl.DataFrame, name: str) -> str:
    """Add one file to the folder rel (a log, like download attempts)."""
    target = path(f"{rel}/{name}")
    if is_s3():
        con = connect()
        con.register("frame", df.to_arrow())
        con.execute(f"COPY frame TO '{target}' (FORMAT parquet, COMPRESSION zstd)")
    else:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(target, compression="zstd")
    return target


def delete_prefix(rel: str) -> None:
    """Remove everything under rel (S3 only; locally replace_folder removes the folder)."""
    import boto3

    bucket, _, key = path(rel).removeprefix("s3://").partition("/")
    s3 = boto3.client("s3")
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=key + "/"):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})


def scan(rel_glob: str) -> str:
    """SQL for every Parquet file matching rel_glob, folder names (state=AZ) as columns.
    Those stay text: autocast would make ccn=030006 the number 30006."""
    return (f"read_parquet('{path(rel_glob)}', hive_partitioning = true, "
            "hive_types_autocast = false, union_by_name = true)")  # fmt: skip


def read(rel_glob: str, con: duckdb.DuckDBPyConnection | None = None,
         sql: str = "SELECT * FROM {}") -> pl.DataFrame:  # fmt: skip
    """sql over every Parquet file matching rel_glob, as one frame (empty if there are no
    files yet)."""
    con = con or connect()
    try:
        return con.execute(sql.format(scan(rel_glob))).pl()
    except duckdb.IOException:  # no files yet
        return pl.DataFrame()
