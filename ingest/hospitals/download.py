"""Download each hospital's machine-readable price file, compressed, and record it.

Usage:
    uv run python -m ingest.hospitals.download [--ccn 030006 ...]

Reads warehouse/seeds/hospital_sources.csv. Each file is streamed (never held in memory),
hashed with SHA-256 as it arrives, and written gzip-compressed to
data/raw/<yyyy-mm-dd>/<ccn>_<file name>.gz. Every attempt is recorded in raw.source_files.
Nothing new is kept when the server says the file hasn't changed (ETag / Last-Modified)
or when its checksum matches the last download.
"""

import argparse
import gzip
import hashlib
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl
import psycopg

from ingest.hospitals.find_sources import BROWSER_USER_AGENT, USER_AGENT

SOURCES_PATH = Path("warehouse/seeds/hospital_sources.csv")
RAW_DIR = Path("data/raw")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://pt:pt@localhost:5432/prices")
ATTEMPTS = 4
CHUNK = 1 << 20  # 1 MiB
# Files larger than this (by Content-Length) are skipped and recorded: the parser holds a
# file in memory, so these wait for a streaming parser (Mayo Clinic Arizona's is 21.5 GB).
MAX_BYTES = 5 * 10**9

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.source_files (
    id            bigserial PRIMARY KEY,
    ccn           text        NOT NULL,
    url           text        NOT NULL,
    attempted_at  timestamptz NOT NULL,
    outcome       text        NOT NULL,  -- downloaded, unchanged, failed
    access        text,                  -- direct, browser_ua_only
    http_status   int,
    format        text,
    sha256        text,
    size_bytes    bigint,
    path          text,
    etag          text,
    last_modified text,
    error         text
);
"""


class RetryableStatus(Exception):
    """A server error worth retrying (5xx, 429)."""


@dataclass
class LastDownload:
    sha256: str
    path: str
    etag: str | None
    last_modified: str | None


def file_format(url: str, content_type: str) -> str:
    """csv, json or zip, from the URL's extension, else the Content-Type."""
    path = httpx.URL(url).path.lower()
    for ext in ("csv", "json", "zip"):
        if path.endswith(f".{ext}"):
            return ext
    for ext in ("csv", "json", "zip"):
        if ext in content_type:
            return ext
    return "unknown"


def conditional_headers(last: LastDownload | None) -> dict[str, str]:
    """Ask the server to answer 304 Not Modified if the file is unchanged."""
    headers = {}
    if last and last.etag:
        headers["If-None-Match"] = last.etag
    if last and last.last_modified:
        headers["If-Modified-Since"] = last.last_modified
    return headers


def stream_to_gzip(response: httpx.Response, dest: Path) -> tuple[str, int]:
    """Write the body gzip-compressed to dest; return (SHA-256 of the original bytes, size)."""
    digest, size = hashlib.sha256(), 0
    part = dest.with_name(dest.name + ".part")
    with gzip.open(part, "wb", compresslevel=6) as out:
        for chunk in response.iter_bytes(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    part.replace(dest)
    return digest.hexdigest(), size


def open_stream(client: httpx.Client, url: str, headers: dict) -> tuple[httpx.Response, str]:
    """Send the request; on a plain 403, retry once as a browser (see find_sources)."""
    response = client.send(client.build_request("GET", url, headers=headers), stream=True)
    if response.status_code == 403 and response.headers.get("cf-mitigated") != "challenge":
        response.close()
        headers = {**headers, "User-Agent": BROWSER_USER_AGENT}
        response = client.send(client.build_request("GET", url, headers=headers), stream=True)
        return response, "browser_ua_only"
    return response, "direct"


def download_once(
    client: httpx.Client, ccn: str, url: str, day_dir: Path, last: LastDownload | None
) -> dict:
    """One attempt. Returns a raw.source_files row; raises on errors worth retrying."""
    response, access = open_stream(client, url, conditional_headers(last))
    try:
        row = {"ccn": ccn, "url": url, "access": access, "http_status": response.status_code}
        if response.status_code == 304 and last:
            return {**row, "outcome": "unchanged", "sha256": last.sha256, "path": last.path}
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableStatus(f"HTTP {response.status_code}")
        if response.status_code != 200:
            return {**row, "outcome": "failed", "error": f"HTTP {response.status_code}"}
        length = int(response.headers.get("content-length") or 0)
        if length > MAX_BYTES:
            return {**row, "outcome": "skipped_too_large", "size_bytes": length,
                    "error": f"{length / 1e9:.1f} GB is over the {MAX_BYTES / 1e9:.0f} GB limit"}  # fmt: skip

        fmt = file_format(url, response.headers.get("content-type", ""))
        day_dir.mkdir(parents=True, exist_ok=True)
        # Some URLs have no file name (".../charges/export", ".../standardcharges-3/").
        name = Path(httpx.URL(url).path).name or "file"
        dest = day_dir / f"{ccn}_{name}.gz"
        sha256, size = stream_to_gzip(response, dest)
        row |= {
            "format": fmt,
            "sha256": sha256,
            "size_bytes": size,
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        }
        if last and sha256 == last.sha256 and Path(last.path).exists():
            dest.unlink()  # same bytes as last time: keep the earlier copy only
            return {**row, "outcome": "unchanged", "path": last.path}
        return {**row, "outcome": "downloaded", "path": dest.as_posix()}
    finally:
        response.close()


def download(
    client: httpx.Client, ccn: str, url: str, day_dir: Path, last: LastDownload | None
) -> dict:
    """download_once with retries and exponential backoff (2, 4, 8 seconds)."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return download_once(client, ccn, url, day_dir, last)
        except (httpx.TransportError, RetryableStatus) as e:
            if attempt == ATTEMPTS:
                return {"ccn": ccn, "url": url, "outcome": "failed", "error": repr(e)}
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def last_download(conn: psycopg.Connection, ccn: str, url: str) -> LastDownload | None:
    row = conn.execute(
        """SELECT sha256, path, etag, last_modified FROM raw.source_files
           WHERE ccn = %s AND url = %s AND outcome = 'downloaded'
           ORDER BY attempted_at DESC LIMIT 1""",
        (ccn, url),
    ).fetchone()
    return LastDownload(*row) if row else None


def record(conn: psycopg.Connection, row: dict, attempted_at: datetime) -> None:
    columns = ["ccn", "url", "outcome", "access", "http_status", "format", "sha256",
               "size_bytes", "path", "etag", "last_modified", "error"]  # fmt: skip
    conn.execute(
        f"INSERT INTO raw.source_files (attempted_at, {', '.join(columns)}) "
        f"VALUES (%s, {', '.join(['%s'] * len(columns))})",
        [attempted_at, *(row.get(c) for c in columns)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ccn", nargs="*", help="only these hospitals")
    args = parser.parse_args()

    sources = pl.read_csv(SOURCES_PATH, infer_schema_length=0).filter(pl.col("mrf_url") != "")
    if args.ccn:
        sources = sources.filter(pl.col("ccn").is_in(args.ccn))
    day_dir = RAW_DIR / datetime.now(UTC).strftime("%Y-%m-%d")

    timeout = httpx.Timeout(60, read=300)
    headers = {"User-Agent": USER_AGENT}
    with (
        psycopg.connect(DATABASE_URL, autocommit=True) as conn,
        httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client,
    ):
        conn.execute(SCHEMA_SQL)
        for s in sources.iter_rows(named=True):
            started = datetime.now(UTC)
            last = last_download(conn, s["ccn"], s["mrf_url"])
            row = download(client, s["ccn"], s["mrf_url"], day_dir, last)
            record(conn, row, started)
            seconds = (datetime.now(UTC) - started).total_seconds()
            size = f"{row['size_bytes'] / 1e6:,.0f} MB" if row.get("size_bytes") else ""
            detail = row.get("error") or row.get("path", "")
            print(f"{s['ccn']}  {row['outcome']:10} {size:>8} {seconds:6.0f}s  {detail}")


if __name__ == "__main__":
    main()
