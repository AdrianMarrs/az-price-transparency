"""Run the hospital pipeline for whole states in one process: the cloud's national pass.

Usage:
    uv run python -m ingest.pipeline --state TX OK [--workers 4] [--limit 10]
                                     [--skip-warehouse] [--fresh-days 7]

For each in-scope hospital of those states with a price file URL
(warehouse/seeds/hospital_sources.csv, from ingest.national.seeds): download the file
(ingest.hospitals.download), parse it (ingest.hospitals.parse) and write its rows to the lake
(ingest.hospitals.load). With DATA_BUCKET set the raw file is kept there and the local
copies are then deleted, so the disk only holds the files in progress. Hospitals run in
parallel worker processes, spawned rather than forked (polars deadlocks in a forked child;
see ingest/insurers/run.py). Files refused with a 403 are retried afterwards in a headless
browser (ingest.hospitals.browser).

Then, unless --skip-warehouse: compliance checks and payer plans for every hospital, dbt
build (the DuckDB warehouse), and with SITE_BUCKET set each state's site files
(serving.export_static).

Files over BIG_BYTES are parsed after the rest, one at a time, each in a fresh process: a
parse holds the file in memory (about 3.5 GB at Arizona's largest, 0.5 GB), so several big
ones at once could exhaust the task's memory, and a worker killed for it would stop every
other. A big file that still runs out fails alone.

For every state at once, run the hospitals on Spot with --skip-warehouse, then the build
with --warehouse-only on on-demand capacity: Spot can be stopped at any time (a trial run
was, 7 minutes in), and a hospital is resumable but a dbt build is not.

Resumable, for a Fargate Spot task that can be stopped at two minutes' notice: a hospital
downloaded in the last --fresh-days whose rows are in the lake is skipped. The download log
and parse results are saved every SAVE_EVERY hospitals and when the run ends or is stopped.
"""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from multiprocessing import get_context
from pathlib import Path

import httpx
import polars as pl

from ingest import lake
from ingest.hospitals import browser, compliance, download, payer_plans, source_log
from ingest.hospitals.find_sources import USER_AGENT
from ingest.hospitals.load import HOSPITALS_PATH, write_hospital
from ingest.hospitals.load import SCHEMA as CHARGES_SCHEMA
from ingest.hospitals.parse import PARSED_DIR, load_shoppable, parse_one
from ingest.insurers.load import KEYS as INSURER_KEYS
from ingest.insurers.normalize import SCHEMA as INSURER_SCHEMA
from ingest.storage import upload

SOURCES_PATH = download.SOURCES_PATH
RAW_DIR = download.RAW_DIR
REPORTS = "raw/parse_reports"  # one file per save, like the download log
SAVE_EVERY = 25
BIG_BYTES = 10**9  # uncompressed; parsed alone, after the rest
ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Job:
    ccn: str
    state: str
    url: str
    last: source_log.LastDownload | None


def hospitals_to_run(states: list[str]) -> pl.DataFrame:
    """ccn, state, mrf_url for the states' in-scope hospitals with a price file URL."""
    hospitals = pl.read_csv(HOSPITALS_PATH, infer_schema_length=0).filter(
        (pl.col("federally_run") == "false") & pl.col("state").is_in([s.upper() for s in states])
    )
    sources = pl.read_csv(SOURCES_PATH, infer_schema_length=0).filter(
        pl.col("mrf_url").fill_null("") != ""
    )
    return hospitals.select("ccn", "state").join(sources.select("ccn", "mrf_url"), on="ccn")


def loaded_hospitals() -> set[str]:
    """Hospitals with rows in the lake."""
    df = lake.read("raw/hospital_charges/*/*/*.parquet", sql="SELECT DISTINCT ccn FROM {}")
    return set(df["ccn"]) if "ccn" in df.columns else set()


def recently_done(attempts: pl.DataFrame, days: int, now: datetime, loaded: set[str]) -> set[str]:
    """Hospitals whose file was downloaded (or found unchanged) in the last `days` days and
    whose rows are in the lake."""
    recent = attempts.filter(
        pl.col("outcome").is_in(["downloaded", "unchanged"])
        & (pl.col("attempted_at") >= now - timedelta(days=days))
    )["ccn"].unique()
    return set(recent) & loaded


def parse_and_load(ccn: str, state: str, path: Path, source_id: int, keep: bool) -> dict:
    """Parse one downloaded file and write its rows to the lake; returns the parse entry.
    Unless keep, deletes the local files after (the raw one is in the data bucket)."""
    entry = parse_one(ccn, path, load_shoppable())
    parsed = PARSED_DIR / f"{ccn}.parquet"
    if parsed.exists() and entry.get("outcome") not in ("failed", "deferred_too_large"):
        df = pl.read_parquet(parsed).with_columns(
            pl.lit(source_id, pl.Int64).alias("source_file_id")
        )
        write_hospital(df, ccn, state)
    if not keep:
        for p in (path, parsed, PARSED_DIR / f"{ccn}_rejects.csv"):
            p.unlink(missing_ok=True)
    return entry


def process(job: Job, day_dir: Path, keep: bool) -> dict:
    """One hospital, in a worker process: download, then parse and load if it's new. Never
    raises: an error (a full disk, a file the parser trips on) fails this hospital only."""
    started = datetime.now(UTC)
    try:
        return process_one(job, day_dir, keep, started)
    except Exception as e:  # noqa: BLE001 - one hospital must not stop the run
        row = {"ccn": job.ccn, "url": job.url, "outcome": "failed", "id": source_log.new_id(started),
               "error": f"{type(e).__name__}: {e}"[:300]}  # fmt: skip
        return {"row": row, "started": started, "entry": None, "state": job.state, "big": False}


def process_one(job: Job, day_dir: Path, keep: bool, started: datetime) -> dict:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True,
                      headers=headers) as client:  # fmt: skip
        row = download.download(client, job.ccn, job.url, day_dir, job.last)
    row["id"] = source_log.new_id(started)
    entry, big = None, False
    if row["outcome"] == "downloaded":
        row["s3_uri"] = upload(Path(row["path"]))
        keep_file = keep or row["s3_uri"] is None  # never delete the only copy
        if (row.get("size_bytes") or 0) > BIG_BYTES:
            big = True  # parsed later, alone (run_big)
        else:
            entry = parse_and_load(job.ccn, job.state, Path(row["path"]), row["id"], keep_file)
    return {"row": row, "started": started, "entry": entry, "state": job.state, "big": big}


def run_big(big: list[tuple[dict, str]], keep: bool) -> list[dict]:
    """Parse and load the big files one at a time, each in a fresh process; returns the
    parse entries (a file that ran out of memory gets a failed one)."""
    entries = []
    for row, state in big:
        keep_file = keep or row.get("s3_uri") is None
        with ProcessPoolExecutor(1, mp_context=get_context("spawn")) as pool:
            future = pool.submit(parse_and_load, row["ccn"], state, Path(row["path"]),
                                 row["id"], keep_file)  # fmt: skip
            try:
                entry = future.result()
            except BrokenProcessPool:
                entry = {"ccn": row["ccn"], "path": row["path"], "outcome": "failed",
                         "error": "the parse ran out of memory"}  # fmt: skip
        print(f"{row['ccn']}  big file ({row['size_bytes'] / 1e9:.1f} GB)  {entry['outcome']}")
        entries.append(entry)
    return entries


def save_reports(entries: list[dict]) -> None:
    if entries:
        stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%S%f}"
        df = (
            pl.DataFrame(entries, infer_schema_length=None)
            .cast(pl.String)
            .with_columns(pl.lit(stamp).alias("parsed_at"))
        )
        lake.append(REPORTS, df, f"{stamp}-{os.getpid()}.parquet")
        entries.clear()


def run_hospitals(states: list[str], workers: int, limit: int | None, fresh_days: int,
                  keep: bool) -> list[dict]:  # fmt: skip
    """Download, parse and load every hospital to run; returns the attempts recorded."""
    log = source_log.Log()
    todo = hospitals_to_run(states)
    loaded = loaded_hospitals()
    done = recently_done(log.before, fresh_days, datetime.now(UTC), loaded)
    done &= set(todo["ccn"])
    todo = todo.filter(~pl.col("ccn").is_in(list(done)))
    if limit:
        todo = todo.head(limit)
    print(f"{todo.height:,} hospitals to run in {', '.join(states)} ({len(done):,} done already)")
    day_dir = RAW_DIR / datetime.now(UTC).strftime("%Y-%m-%d")
    # A hospital not in the lake is downloaded afresh: an "unchanged" answer would leave it
    # with no rows (the earlier copy isn't on this machine).
    jobs = [Job(r["ccn"], r["state"], r["mrf_url"],
                log.last(r["ccn"], r["mrf_url"]) if r["ccn"] in loaded else None)
            for r in todo.iter_rows(named=True)]  # fmt: skip
    rows, entries, blocked, big = [], [], [], []
    pool = ProcessPoolExecutor(workers, mp_context=get_context("spawn"))
    started = time.time()
    try:
        pending = {pool.submit(process, j, day_dir, keep) for j in jobs}
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for f in finished:
                r = f.result()
                row = r["row"]
                log.record(row, r["started"])
                rows.append(row)
                if r["entry"]:
                    entries.append(r["entry"])
                if row["outcome"] == "failed" and row.get("http_status") == 403:
                    blocked.append((row, r["state"]))
                if r["big"]:
                    big.append((row, r["state"]))
                n = len(rows)
                size = f"{row['size_bytes'] / 1e6:,.0f} MB" if row.get("size_bytes") else ""
                parsed = "big: later" if r["big"] else (r["entry"] or {}).get("outcome", "")
                print(f"[{n}/{len(jobs)} {time.time() - started:,.0f}s] {row['ccn']}  "
                      f"{row['outcome']:10} {size:>8}  {parsed:17} {row.get('error') or ''}")  # fmt: skip
                if n % SAVE_EVERY == 0:
                    log.save()
                    save_reports(entries)
    finally:
        log.save()
        save_reports(entries)
        pool.shutdown(wait=False, cancel_futures=True)
    if big:
        print(f"{len(big)} big files, parsed one at a time")
        save_reports(run_big(big, keep))
    if blocked and browser.enabled():
        rows += fetch_blocked(blocked, day_dir, keep)
    return rows


def fetch_blocked(blocked: list[tuple[dict, str]], day_dir: Path, keep: bool) -> list[dict]:
    """Files refused with a 403, retried in a browser; parsed and loaded like the rest."""
    print(f"{len(blocked)} refused programs; trying them in a browser")
    states = {row["ccn"]: state for row, state in blocked}
    tmp = RAW_DIR / "browser"
    rows, entries = [], []
    with source_log.Log() as log:
        for f in browser.fetch_files([(row["ccn"], row["url"]) for row, _ in blocked], tmp):
            if f.path is None:
                print(f"{f.ccn}  still blocked in a browser ({f.error})")
                continue
            started = datetime.now(UTC)
            row = download.import_file(f.ccn, f.path, f.url, day_dir, access="browser_download")
            row["s3_uri"] = upload(Path(row["path"]))
            row["id"] = log.record(row, started)
            shutil.rmtree(f.path.parent, ignore_errors=True)
            entry = parse_and_load(f.ccn, states[f.ccn], Path(row["path"]), row["id"],
                                   keep or row["s3_uri"] is None)  # fmt: skip
            entries.append(entry)
            rows.append(row)
            print(f"{f.ccn}  downloaded in a browser ({f.mode})  {entry.get('outcome')}")
    save_reports(entries)
    return rows


LOADED_AT = {"loaded_at": pl.Datetime("us", "UTC")}
# Each raw table's folder (at the depth dbt's views read) and columns, for ensure_tables.
TABLES = {
    "raw/hospital_charges/state=_/ccn=_": CHARGES_SCHEMA | LOADED_AT,
    "raw/insurer_rates/insurer=_/month=_/network=_":
        {c: t for c, t in INSURER_SCHEMA.items() if c not in INSURER_KEYS} | LOADED_AT,
    "raw/source_files": source_log.SCHEMA,
}  # fmt: skip


def ensure_tables() -> list[str]:
    """Give each raw table with no files yet an empty one with its columns, so dbt's views
    exist and the models build (a new lake has no insurer rates, for one). Returns them."""
    made = []
    for folder, schema in TABLES.items():
        table = "/".join(folder.split("/")[:2])
        depth = folder.count("/") - 1
        if not lake.files(f"{table}/{'*/' * depth}*.parquet"):
            made.append(lake.append(folder, pl.DataFrame(schema=schema), "empty.parquet"))
    return made


def build_warehouse(states: list[str]) -> None:
    """Compliance and payer plans for every hospital, dbt build, then each state's files."""
    ensure_tables()
    compliance.main()
    payer_plans.main()
    subprocess.run(["dbt", "build", "--project-dir", "warehouse", "--profiles-dir", "warehouse"],
                   cwd=ROOT, check=True)  # fmt: skip
    if os.environ.get("SITE_BUCKET"):
        from serving import export_static  # boto3 and the warehouse only when exporting

        export_static.export_states(states)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", nargs="+", required=True, help="two-letter state codes")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    parser.add_argument("--limit", type=int, help="at most this many hospitals (a trial run)")
    parser.add_argument("--fresh-days", type=int, default=7,
                        help="skip hospitals downloaded this recently and in the lake")  # fmt: skip
    parser.add_argument("--skip-warehouse", action="store_true",
                        help="only download, parse and load")  # fmt: skip
    parser.add_argument("--warehouse-only", action="store_true",
                        help="skip the hospitals; only build the warehouse and site files "
                             "(on-demand capacity: a build can't resume after a Spot stop)")  # fmt: skip
    parser.add_argument("--keep-files", action="store_true",
                        help="keep local raw and parsed files (always kept without DATA_BUCKET)")  # fmt: skip
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    # A Spot interruption sends SIGTERM: unwind through the finally blocks, which save the log.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if args.warehouse_only:
        build_warehouse(args.state)
        return
    rows = run_hospitals(args.state, args.workers, args.limit, args.fresh_days, args.keep_files)
    outcomes = pl.DataFrame(
        {"outcome": [r["outcome"] for r in rows]}, schema={"outcome": pl.String}
    )
    print(outcomes["outcome"].value_counts(sort=True))
    if not args.skip_warehouse:
        build_warehouse(args.state)


if __name__ == "__main__":
    main()
