"""Monthly cloud run: every in-network file in an insurer's table of contents, in parallel.

Usage:
    uv run python -m ingest.insurers.run [--insurer cigna] [--network arizona-hmo ...]
                                         [--workers N] [--skip-failed]

Finds the current table of contents from the insurer's published pointer (Cigna:
cigna.com/static/mrf/latest.json, which carries the signed index URL and the reporting
month), then streams each in-network file (ingest.insurers.tic), normalizes it to Parquet
(ingest.insurers.normalize) and uploads both to the data bucket. Files run in separate
processes, one per CPU: parsing, not the download, is the limit.

Resumable. Each file's status is a DynamoDB item (RUNS_TABLE), PK RUN#<insurer>#<month>,
SK FILE#<name>: queued, done (with its stats) or failed (with the error). A rerun for the
same month skips files that are done; failed and interrupted ones run again unless
--skip-failed. Each run adds a SUMMARY#<start time> item: files, hours and estimated Fargate cost.

Without RUNS_TABLE (a laptop), status is kept in memory only.
"""

import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal

import boto3
import httpx

from ingest.insurers.normalize import PARQUET_DIR, network_name, normalize_file
from ingest.insurers.tic import USER_AGENT, hospital_npis, load_toc, output_path, run_file
from ingest.storage import upload

POINTERS = {"cigna": "https://www.cigna.com/static/mrf/latest.json"}

# Fargate, us-east-2, Linux/ARM (per hour). Used for the estimate in the SUMMARY items; the
# actual charge is checked against Cost Explorer afterwards.
FARGATE_VCPU_HOUR = 0.03238
FARGATE_GB_HOUR = 0.00356


def current_toc(insurer: str) -> tuple[str, str]:
    """(signed table-of-contents URL, reporting month yyyy-mm) from the insurer's pointer."""
    with httpx.Client(timeout=60, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT}) as c:  # fmt: skip
        r = c.get(POINTERS[insurer])
        r.raise_for_status()
        return toc_from_pointer(r.json())


def toc_from_pointer(pointer: dict) -> tuple[str, str]:
    """Cigna's latest.json lists its machine-readable files by program and kind."""
    for mrf in pointer["mrfs"]:
        if mrf.get("kind") == "TOC" and mrf.get("program") == "cost_transparency":
            return mrf["files"][0]["url"], mrf["extra_fields"]["reporting_month"]
    raise ValueError("no cost transparency table of contents in the pointer")


def all_in_network_files(toc: dict, networks: list[str] | None = None) -> dict[str, str]:
    """File name -> signed URL for each distinct in-network file (optionally only those
    whose name contains one of `networks`), smallest names first for a stable order."""
    files = {}
    for s in toc["reporting_structure"]:
        for f in s.get("in_network_files", []):
            name = f["location"].split("?")[0].rsplit("/", 1)[-1]
            if networks and not any(n in name for n in networks):
                continue
            files.setdefault(name, f["location"])
    return dict(sorted(files.items()))


class Status:
    """Per-file status in DynamoDB, or in memory without a table."""

    def __init__(self, insurer: str, month: str, table_name: str | None = None, table=None):
        self.pk = f"RUN#{insurer}#{month}"
        self.table = table or (boto3.resource("dynamodb").Table(table_name) if table_name else None)
        self.memory: dict[str, dict] = {}

    def all(self) -> dict[str, dict]:
        if self.table is None:
            return dict(self.memory)
        items, kwargs = {}, {"KeyConditionExpression": "PK = :pk",
                             "ExpressionAttributeValues": {":pk": self.pk}}  # fmt: skip
        while True:
            page = self.table.query(**kwargs)
            for item in page["Items"]:
                if item["SK"].startswith("FILE#"):
                    items[item["SK"].removeprefix("FILE#")] = item
            if "LastEvaluatedKey" not in page:
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def put(self, sk: str, **fields) -> None:
        item = {"PK": self.pk, "SK": sk, "updated_at": now()} | to_dynamo(fields)
        if self.table is None:
            self.memory[sk.removeprefix("FILE#")] = item
        else:
            self.table.put_item(Item=item)

    def file(self, name: str, status: str, **fields) -> None:
        self.put(f"FILE#{name}", status=status, **fields)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def to_dynamo(value):
    """Floats become Decimal (DynamoDB has no float type); None values are dropped."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    return value


def process_file(url: str, insurer: str, month: str) -> dict:
    """Stream, normalize and upload one file (runs in a worker process)."""
    stats = run_file(url, insurer, month, hospital_npis())
    raw = output_path(insurer, month, url)
    df = normalize_file(raw, insurer, month)
    dest = PARQUET_DIR / f"insurer={insurer}" / f"month={month}" / f"{network_name(raw)}.parquet"
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(dest)
    parquet_uri = upload(dest)
    if os.environ.get("DATA_BUCKET") and not (stats["s3_uri"] and parquet_uri):
        raise RuntimeError("upload to the data bucket failed")
    if parquet_uri:  # the bucket has both; keep the task's disk small
        raw.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
    keep = ("references", "kept_groups", "codes", "kept_codes", "compressed", "refs_first",
            "pass1_compressed", "inline_group_rates", "seconds", "mb_per_s", "s3_uri")  # fmt: skip
    return {k: stats[k] for k in keep if k in stats} | {
        "rows": df.height,
        "hospitals": df["ccn"].n_unique(),
        "parquet_uri": parquet_uri,
    }


def run(insurer: str, networks: list[str] | None, workers: int, skip_failed: bool,
        status_table: str | None = None, table=None) -> dict:  # fmt: skip
    started, t0 = now(), time.perf_counter()
    toc_url, month = current_toc(insurer)
    files = all_in_network_files(load_toc(toc_url), networks)
    status = Status(insurer, month, status_table, table)
    previous = status.all()
    skip = {"done"} | ({"failed"} if skip_failed else set())
    todo = {n: u for n, u in files.items() if previous.get(n, {}).get("status") not in skip}
    print(f"{insurer} {month}: {len(files)} files, {len(files) - len(todo)} already done "
          f"or skipped, {len(todo)} to run on {workers} workers")  # fmt: skip
    done = failed = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for name, url in todo.items():
            status.file(name, "queued", queued_at=now())
            futures[pool.submit(process_file, url, insurer, month)] = name
        for future in as_completed(futures):
            name = futures[future]
            try:
                stats = future.result()
            except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
                failed += 1
                status.file(name, "failed", error=f"{type(e).__name__}: {e}"[:1000],
                            trace=traceback.format_exc()[-3000:])  # fmt: skip
                print(f"FAILED {name}: {e}")
            else:
                done += 1
                status.file(name, "done", finished_at=now(), **stats)
                print(f"done {name}: {stats['rows']:,} rows, {stats['seconds']}s, "
                      f"{stats['mb_per_s']} MB/s")  # fmt: skip
    summary = summarize(started, time.perf_counter() - t0, files, status.all(), done, failed)
    status.put(f"SUMMARY#{started}", **summary)  # one per run: a resume keeps the first
    return summary


def summarize(started: str, seconds: float, files: dict, items: dict, done: int,
              failed: int) -> dict:  # fmt: skip
    vcpu = float(os.environ.get("TASK_VCPU", "0") or 0)
    memory_gb = float(os.environ.get("TASK_MEMORY_GB", "0") or 0)
    hours = seconds / 3600
    statuses = [items.get(n, {}).get("status") for n in files]
    return {
        "started_at": started, "finished_at": now(), "hours": round(hours, 3),
        "files": len(files), "done_this_run": done, "failed_this_run": failed,
        "done_total": statuses.count("done"), "failed_total": statuses.count("failed"),
        "rows": sum(int(i.get("rows", 0)) for i in items.values() if i.get("status") == "done"),
        "task_vcpu": vcpu or None, "task_memory_gb": memory_gb or None,
        "estimated_cost_usd": round(hours * (vcpu * FARGATE_VCPU_HOUR + memory_gb * FARGATE_GB_HOUR), 4)
        if vcpu else None,
    }  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--insurer", default="cigna", choices=sorted(POINTERS))
    parser.add_argument("--network", action="append", help="only files whose name contains this")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--skip-failed", action="store_true", help="don't retry failed files")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    summary = run(args.insurer, args.network, args.workers, args.skip_failed,
                  os.environ.get("RUNS_TABLE"))  # fmt: skip
    print(summary)
    sys.exit(1 if summary["failed_total"] else 0)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    main()
