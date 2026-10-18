"""Download each hospital's machine-readable price file, compressed, and record it.

Usage:
    uv run python -m ingest.hospitals.download [--ccn 030006 ...]
    uv run python -m ingest.hospitals.download --import-file 030023 path/to/file.zip
    uv run python -m ingest.hospitals.download --fetch-in-browser [--ccn 030023 ...]

Reads warehouse/seeds/hospital_sources.csv. Each file is streamed (never held in memory),
hashed with SHA-256 as it arrives, and written gzip-compressed to
data/raw/<yyyy-mm-dd>/<ccn>_<file name>.gz. Every attempt is recorded in raw.source_files
(ingest/hospitals/source_log.py, in the Parquet lake).
Nothing new is kept when the server says the file hasn't changed (ETag / Last-Modified)
or when its checksum matches the last download.

A file refused with a 403 (a bot check that turns away programs) is then fetched with a
real browser, Edge driven by Playwright (ingest/hospitals/browser.py), and recorded with
access browser_download. Compliance still counts the download rule as failed for these.

--import-file takes a file downloaded by hand in a browser, for one the automated browser
can't get either (a CAPTCHA), and records it with access manual_download.

--fetch-in-browser helps with that hand download: it opens each blocked price file's URL in
your default browser, waits for the file to land in your Downloads folder, and imports it.
By default it covers every hospital fetched by a browser before.
"""

import argparse
import gzip
import hashlib
import os
import sys
import time
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl

from ingest.hospitals import browser, source_log
from ingest.hospitals.find_sources import BROWSER_USER_AGENT, USER_AGENT
from ingest.hospitals.source_log import LastDownload
from ingest.storage import upload

SOURCES_PATH = Path("warehouse/seeds/hospital_sources.csv")
RAW_DIR = Path("data/raw")
ATTEMPTS = 4
CHUNK = 1 << 20  # 1 MiB
# Files larger than this (by Content-Length) are skipped and recorded: the parser holds a
# file in memory, so these wait for a streaming parser (Mayo Clinic Arizona's is 21.5 GB).
MAX_BYTES = 5 * 10**9
DOWNLOADS_DIR = Path(os.environ.get("DOWNLOADS_DIR", Path.home() / "Downloads"))
BROWSER_WAIT_SECONDS = 600


class RetryableStatus(Exception):
    """A server error worth retrying (5xx, 429)."""


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


def import_file(ccn: str, src: Path, url: str, day_dir: Path,
                access: str = "manual_download") -> dict:  # fmt: skip
    """Store a file downloaded by hand as data/raw/<day>/<ccn>_<name>.gz; returns its row.
    The name comes from the URL when there is one, since a browser renames a repeat
    download ("file (1).zip")."""
    day_dir.mkdir(parents=True, exist_ok=True)
    name = (Path(httpx.URL(url).path).name if url else "") or src.name
    dest = day_dir / f"{ccn}_{name}.gz"
    digest, size = hashlib.sha256(), 0
    part = dest.with_name(dest.name + ".part")
    with src.open("rb") as f, gzip.open(part, "wb", compresslevel=6) as out:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    part.replace(dest)
    return {"ccn": ccn, "url": url, "outcome": "downloaded", "access": access,
            "format": file_format(src.name, ""), "sha256": digest.hexdigest(),
            "size_bytes": size, "path": dest.as_posix()}  # fmt: skip


def import_manual(ccn: str, src: Path, access: str = "manual_download") -> dict:
    """import_file for one hospital, using its price file URL from the sources seed."""
    sources = pl.read_csv(SOURCES_PATH, infer_schema_length=0).filter(pl.col("ccn") == ccn)
    if sources.is_empty():
        raise SystemExit(f"{ccn} is not in {SOURCES_PATH}")
    url = sources["mrf_url"][0] or ""
    expected = Path(httpx.URL(url).path).name if url else ""
    if expected and not matches_download(src.name, expected):
        print(f"note: {src.name} is not the file named in the sources seed ({url})")
    started = datetime.now(UTC)
    with source_log.Log() as log:
        last = log.last(ccn, url)
        row = import_file(ccn, src, url, RAW_DIR / started.strftime("%Y-%m-%d"), access)
        if last and last.sha256 == row["sha256"] and Path(last.path).exists():
            if Path(row["path"]) != Path(last.path):
                Path(row["path"]).unlink()  # same bytes as last time: keep the earlier copy
            row |= {"outcome": "unchanged", "path": last.path}
        else:
            row["s3_uri"] = upload(Path(row["path"]))
        log.record(row, started)
    print(f"{ccn}  {row['outcome']} {row['size_bytes'] / 1e6:,.0f} MB  {row['path']}")
    return row


def matches_download(name: str, expected: str) -> bool:
    """True for the expected file name or a browser's renamed repeat: "name (1).zip" (Edge,
    Chrome) or "name(1).zip" (Firefox)."""
    stem, suffix = Path(expected).stem, Path(expected).suffix
    if name == expected:
        return True
    if not (name.startswith(stem) and name.endswith(suffix)):
        return False
    middle = name.removeprefix(stem).removesuffix(suffix).lstrip(" ")
    return middle.startswith("(") and middle.endswith(")") and middle[1:-1].isdigit()


def new_download(folder: Path, expected: str, since: float) -> Path | None:
    """The newest finished download of `expected` in folder since `since`, if any. None
    while any download is still in progress (Firefox's .part, Chrome and Edge's
    .crdownload), since Firefox creates the final file empty before filling it."""
    recent = [p for p in folder.iterdir() if p.is_file() and p.stat().st_mtime > since]
    if any(p.suffix in (".part", ".crdownload") for p in recent):
        return None
    found = [p for p in recent if p.stat().st_size > 0 and matches_download(p.name, expected)]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def wait_for_download(expected: str, since: float) -> Path | None:
    """Poll DOWNLOADS_DIR until the file appears and its size holds steady."""
    size, deadline = -1, time.time() + BROWSER_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(2)
        found = new_download(DOWNLOADS_DIR, expected, since)
        if found and found.stat().st_size == size:
            return found
        size = found.stat().st_size if found else -1
    return None


def fetch_in_browser(ccns: list[str] | None = None) -> list[dict]:
    """Open each blocked price file in the browser, wait for the download, import it."""
    if not ccns:
        attempts = source_log.read()
        ccns = (
            attempts.filter(pl.col("access").is_in(["manual_download", "browser_download"]))["ccn"]
            .unique()
            .to_list()
        )
    if not ccns:
        raise SystemExit("no hospital has been imported by hand yet; name them with --ccn")
    sources = pl.read_csv(SOURCES_PATH, infer_schema_length=0).filter(pl.col("ccn").is_in(ccns))
    rows = []
    for s in sources.iter_rows(named=True):
        expected = Path(httpx.URL(s["mrf_url"]).path).name
        since = time.time() - 1
        print(f"{s['ccn']}  opening {s['mrf_url']}")
        webbrowser.open(s["mrf_url"])
        path = wait_for_download(expected, since)
        if path is None:
            print(f"{s['ccn']}  no {expected} in {DOWNLOADS_DIR} after {BROWSER_WAIT_SECONDS}s")
            continue
        rows.append(import_manual(s["ccn"], path))
    return rows


def download_hospitals(ccns: list[str] | None = None) -> list[dict]:
    """Download (or confirm unchanged) each hospital's price file; returns the rows recorded.
    Hospitals with no price file URL are skipped. Used by main() and by Dagster."""
    sources = pl.read_csv(SOURCES_PATH, infer_schema_length=0).filter(pl.col("mrf_url") != "")
    if ccns:
        sources = sources.filter(pl.col("ccn").is_in(ccns))
    day_dir = RAW_DIR / datetime.now(UTC).strftime("%Y-%m-%d")

    rows = []
    timeout = httpx.Timeout(60, read=300)
    headers = {"User-Agent": USER_AGENT}
    with (
        source_log.Log() as log,
        httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client,
    ):
        for s in sources.iter_rows(named=True):
            started = datetime.now(UTC)
            last = log.last(s["ccn"], s["mrf_url"])
            row = download(client, s["ccn"], s["mrf_url"], day_dir, last)
            if row["outcome"] == "downloaded":
                row["s3_uri"] = upload(Path(row["path"]))
            log.record(row, started)
            seconds = (datetime.now(UTC) - started).total_seconds()
            size = f"{row['size_bytes'] / 1e6:,.0f} MB" if row.get("size_bytes") else ""
            detail = row.get("error") or row.get("path", "")
            print(f"{s['ccn']}  {row['outcome']:10} {size:>8} {seconds:6.0f}s  {detail}")
            rows.append(row | {"seconds": seconds})
    blocked = [r for r in rows if r["outcome"] == "failed" and r.get("http_status") == 403]
    if blocked and browser.enabled():
        fetched = {r["ccn"]: r for r in fetch_blocked(blocked)}
        rows = [fetched.get(r["ccn"], r) if r in blocked else r for r in rows]
    return rows


def fetch_blocked(rows: list[dict]) -> list[dict]:
    """Fetch files refused with a 403 using a real browser, and import what it gets."""
    print(f"{len(rows)} refused programs; trying them in Edge")
    tmp = RAW_DIR / "browser"
    out = []
    for f in browser.fetch_files([(r["ccn"], r["url"]) for r in rows], tmp):
        if f.path is None:
            print(f"{f.ccn}  still blocked in a browser ({f.error}); see --fetch-in-browser")
            continue
        out.append(import_manual(f.ccn, f.path, access="browser_download") | {"mode": f.mode})
        f.path.unlink(missing_ok=True)
        f.path.parent.rmdir()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ccn", nargs="*", help="only these hospitals")
    parser.add_argument("--import-file", nargs=2, metavar=("CCN", "PATH"),
                        help="store a price file downloaded by hand instead of downloading")  # fmt: skip
    parser.add_argument("--fetch-in-browser", action="store_true",
                        help="open blocked price files in the browser and import the downloads")  # fmt: skip
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # progress shows while waiting on a browser
    if args.fetch_in_browser:
        fetch_in_browser(args.ccn)
    elif args.import_file:
        import_manual(args.import_file[0], Path(args.import_file[1]))
    else:
        download_hospitals(args.ccn)


if __name__ == "__main__":
    main()
