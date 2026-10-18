"""raw.source_files: every attempt to download a hospital's price file, in the lake.

Each run adds one Parquet file (raw/source_files/<time>-<random>.parquet), written when the
run ends, even on an error, so runs in parallel (Dagster runs one per hospital) never write
the same file. An attempt's id is its time in microseconds: unique without a counter to
share between runs, and in time order.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

import polars as pl

from ingest import lake

FOLDER = "raw/source_files"
SCHEMA = {
    "id": pl.Int64,
    "ccn": pl.String,
    "url": pl.String,
    "attempted_at": pl.Datetime("us", "UTC"),
    "outcome": pl.String,  # downloaded, unchanged, failed, skipped_too_large
    "access": pl.String,  # direct, browser_ua_only, browser_download, manual_download
    "http_status": pl.Int32,
    "format": pl.String,
    "sha256": pl.String,
    "size_bytes": pl.Int64,
    "path": pl.String,
    "etag": pl.String,
    "last_modified": pl.String,
    "error": pl.String,
    "s3_uri": pl.String,  # the copy in the data bucket, if uploaded
}


@dataclass
class LastDownload:
    sha256: str
    path: str
    etag: str | None
    last_modified: str | None


def read() -> pl.DataFrame:
    """Every attempt so far (an empty frame with the columns before the first run)."""
    df = lake.read(f"{FOLDER}/*.parquet")
    if df.is_empty():
        return pl.DataFrame(schema=SCHEMA)
    return df.select(pl.col(c).cast(t) if c in df.columns else pl.lit(None, t).alias(c)
                     for c, t in SCHEMA.items())  # fmt: skip


def latest(df: pl.DataFrame) -> dict[str, dict]:
    """Each hospital's most recent attempt."""
    newest = df.sort("attempted_at").group_by("ccn").last()
    return {r["ccn"]: r for r in newest.to_dicts()}


def downloaded_id(df: pl.DataFrame, path: str) -> int | None:
    """The id of the latest download that wrote path."""
    match = df.filter((pl.col("path") == path) & (pl.col("outcome") == "downloaded"))
    return match["id"].max() if match.height else None


class Log:
    """The attempts read once at the start of a run, plus the run's own, saved on exit:

    with Log() as log:
        last = log.last(ccn, url)
        log.record(row, started)
    """

    def __init__(self) -> None:
        self.before = read()
        self.new: list[dict] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.save()

    def frame(self) -> pl.DataFrame:
        return pl.concat([self.before, pl.DataFrame(self.new, schema=SCHEMA)])

    def last(self, ccn: str, url: str) -> LastDownload | None:
        """The latest download of this URL for this hospital."""
        rows = (self.frame().filter((pl.col("ccn") == ccn) & (pl.col("url") == url)
                                    & (pl.col("outcome") == "downloaded"))
                .sort("attempted_at"))  # fmt: skip
        if rows.is_empty():
            return None
        r = rows.row(-1, named=True)
        return LastDownload(r["sha256"], r["path"], r["etag"], r["last_modified"])

    def record(self, row: dict, attempted_at: datetime) -> int:
        """Add one attempt; returns its id."""
        attempted_at = attempted_at.astimezone(UTC)
        id_ = int(attempted_at.timestamp() * 1_000_000)
        while any(r["id"] == id_ for r in self.new):  # two in the same microsecond
            id_ += 1
        self.new.append({c: row.get(c) for c in SCHEMA} | {"id": id_, "attempted_at": attempted_at})
        return id_

    def save(self) -> str | None:
        """Write this run's attempts as one file; returns its path (None if there were none)."""
        if not self.new:
            return None
        first = min(r["attempted_at"] for r in self.new)
        name = f"{first:%Y%m%dT%H%M%S%f}-{secrets.token_hex(3)}.parquet"
        target = lake.append(FOLDER, pl.DataFrame(self.new, schema=SCHEMA), name)
        self.before, self.new = self.frame(), []
        return target
