"""Export the site's data as static JSON files on S3, served by the site's CloudFront.

Usage:
    uv run python -m serving.export_static [--dry-run] [--out DIR]

Replaces the DynamoDB table and the Lambda API (docs/03-cloud.md): every answer the site
needs is precomputed, gzip-compressed, and uploaded next to the site, under one folder per
state so a national version never needs one huge file per service:

    data/<state>/services/<slug>.json  every hospital's prices for one service
                                       (what GET /services/{id}/prices returned)
    data/<state>/providers/<ccn>.json  one hospital: score, shoppable prices
    data/<state>/search.json           the service list, searched in the browser

Only files whose bytes changed are uploaded (S3's ETag is the MD5 of a single-part upload,
so it's compared with the new file's), and files no longer produced are deleted. Writes
are deterministic (gzip without a timestamp), so a rerun with the same data uploads nothing.

Reads the dbt serving models (serving.srv_service_prices and srv_hospital_profiles)
and marts.dim_services from the DuckDB warehouse (WAREHOUSE, data/warehouse.duckdb). Needs
SITE_BUCKET; with SITE_DISTRIBUTION_ID set and anything changed, it clears /data/<state>/*
from the site's CloudFront cache.
"""

import argparse
import gzip
import hashlib
import json
import os
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import boto3
import duckdb

from serving.services import compact, services_list

WAREHOUSE = os.environ.get("WAREHOUSE", "data/warehouse.duckdb")

STATE = "az"
NOTE = "Published hospital standard charges, not a quote. Check with your insurer and hospital."
CACHE_CONTROL = "public, max-age=300, s-maxage=86400"  # as the API's; cleared after an export
UPLOAD_THREADS = 16  # one at a time, the first export of 13,000 files took over ten minutes
# What a service file says about each hospital (the API's projection of the profile).
HOSPITAL_FIELDS = ("ccn", "name", "city", "county", "score_pct", "hospital_type")


def slug(service_id: str) -> str:
    """The site's name for a service (web/app/lib/catalog.ts): cpt-hcpcs:73721 -> cpt-73721,
    ms-drg:470 -> drg-470. Ids have a colon, which a file name (or S3 key on Windows) can't."""
    return service_id.replace("cpt-hcpcs:", "cpt-").replace("ms-drg:", "drg-")


def encode(value) -> bytes:
    """Compact JSON, gzip-compressed with no timestamp, so equal data gives equal bytes."""
    data = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return gzip.compress(data, compresslevel=9, mtime=0)


def profiles(conn: duckdb.DuckDBPyConnection, state: str = STATE) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT item FROM serving.srv_hospital_profiles WHERE lower(state) = ?", [state.lower()]
    ).fetchall()
    found = {}
    for (item,) in rows:
        p = compact(json.loads(item))
        found[p["ccn"]] = p
    return found


PRICE_COLUMNS = ("service_key", "ccn", "payer_name", "plan_name", "payer_group", "market",
                 "setting", "price_type", "methodology", "amount", "algorithm", "bundled", "n")  # fmt: skip


def number(x: float | None) -> float | int | None:
    """1346.0 -> 1346, so whole amounts are written as Postgres wrote them."""
    return int(x) if isinstance(x, float) and x.is_integer() else x


def hospital_item(ccn: str, rows: list[dict]) -> dict:
    """One hospital's part of a service file from its srv_service_prices rows: insurer
    prices, the standard (list, cash, min, max) prices, and how many plans it lists."""
    prices = sorted(
        (compact({"payer": r["payer_name"], "plan": r["plan_name"], "group": r["payer_group"],
                  "market": r["market"], "setting": r["setting"], "type": r["price_type"],
                  "method": r["methodology"], "amount": number(r["amount"]),
                  "algorithm": r["algorithm"], "bundled": r["bundled"], "n": r["n"]})
         for r in rows if r["payer_name"] is not None),
        key=lambda p: (p["payer"], p.get("plan", ""), p["setting"], p["type"]),
    )  # fmt: skip
    standard = sorted(
        (compact({"setting": r["setting"], "type": r["price_type"],
                  "amount": number(r["amount"]), "n": r["n"]})
         for r in rows if r["payer_name"] is None),
        key=lambda p: (p["setting"], p["type"]),
    )  # fmt: skip
    plans = len({(r["payer_name"], r["plan_name"]) for r in rows if r["payer_name"] is not None})
    return {"ccn": ccn, "plans": plans, "standard": standard, "prices": prices}


def service_items(conn: duckdb.DuckDBPyConnection, state: str = STATE
                  ) -> Iterator[tuple[str, list[dict]]]:  # fmt: skip
    """(service key, every hospital's item for it), streamed one service at a time from
    srv_service_prices, so memory holds one service, not the state."""
    cur = conn.execute(
        f"SELECT {', '.join(PRICE_COLUMNS)} FROM serving.srv_service_prices "
        "WHERE lower(state) = ? ORDER BY service_key, ccn",
        [state.lower()],
    )
    key, ccn, items, rows = None, None, [], []
    while batch := cur.fetchmany(5000):
        for values in batch:
            r = dict(zip(PRICE_COLUMNS, values, strict=True))
            if (r["service_key"], r["ccn"]) != (key, ccn) and rows:
                items.append(hospital_item(ccn, rows))
                rows = []
            if r["service_key"] != key and items:
                yield key, items
                items = []
            key, ccn = r["service_key"], r["ccn"]
            rows.append(r)
    if rows:
        items.append(hospital_item(ccn, rows))
    if items:
        yield key, items


def compare(service: dict, items: list[dict], hospitals: dict[str, dict]) -> dict:
    """The service file: what the API's compare() returned with no filters."""
    rows = []
    for i in items:
        p = hospitals.get(i["ccn"], {"ccn": i["ccn"]})
        rows.append({"hospital": {k: p[k] for k in HOSPITAL_FIELDS if k in p},
                     "plans": i.get("plans", 0), "standard": i.get("standard", []),
                     "prices": i.get("prices", [])})  # fmt: skip
    rows.sort(key=lambda r: r["hospital"].get("name", ""))
    return {"service": service, "hospitals": rows, "note": NOTE}


def build(conn: duckdb.DuckDBPyConnection, state: str = STATE) -> Iterator[tuple[str, bytes]]:
    """(S3 key, gzip bytes) for every file."""
    prefix = f"data/{state}"
    services = services_list(conn, state)
    yield f"{prefix}/search.json", encode(services)
    hospitals = profiles(conn, state)
    for ccn, p in hospitals.items():
        yield f"{prefix}/providers/{ccn}.json", encode(p | {"note": NOTE})
    by_key = {s["key"]: s for s in services}
    for key, items in service_items(conn, state):
        if (service := by_key.get(key)) is not None:
            yield (
                f"{prefix}/services/{slug(service['id'])}.json",
                encode(compare(service, items, hospitals)),
            )


def existing(client, bucket: str, prefix: str) -> dict[str, str]:
    """Key -> MD5 of what's in the bucket now."""
    found = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            found[o["Key"]] = o["ETag"].strip('"')
    return found


def sync(files: Iterable[tuple[str, bytes]], bucket: str | None, state: str = STATE,
         client=None, out: Path | None = None, dry_run: bool = False) -> dict:  # fmt: skip
    """Upload the files whose bytes changed and delete the ones no longer produced; returns
    counts. With out, also writes the files there (uncompressed), for a look or for local
    development."""
    client = client or (boto3.client("s3") if bucket else None)
    before = existing(client, bucket, f"data/{state}/") if bucket else {}
    counts = {"files": 0, "bytes": 0, "put": 0, "deleted": 0}
    seen = set()

    def put(key: str, body: bytes) -> None:
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json",
                          ContentEncoding="gzip", CacheControl=CACHE_CONTROL)  # fmt: skip

    with ThreadPoolExecutor(UPLOAD_THREADS) as pool:
        pending = set()
        for key, body in files:
            seen.add(key)
            counts["files"] += 1
            counts["bytes"] += len(body)
            if out:
                path = out / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(gzip.decompress(body))
            if bucket and before.get(key) != hashlib.md5(body).hexdigest():
                counts["put"] += 1
                if not dry_run:
                    if len(pending) >= 4 * UPLOAD_THREADS:  # don't hold every file in memory
                        done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        for f in done:
                            f.result()
                    pending.add(pool.submit(put, key, body))
        for f in pending:
            f.result()  # an upload's error surfaces here, before anything is deleted
    removed = sorted(set(before) - seen)
    counts["deleted"] = len(removed)
    if bucket and removed and not dry_run:
        for i in range(0, len(removed), 1000):
            client.delete_objects(Bucket=bucket, Delete={
                "Objects": [{"Key": k} for k in removed[i : i + 1000]], "Quiet": True})  # fmt: skip
    return counts


def invalidate(distribution_id: str, state: str = STATE, client=None) -> str:
    """Clear the data files from the site's CloudFront cache (one path, of 1,000 free)."""
    response = (client or boto3.client("cloudfront")).create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={"Paths": {"Quantity": 1, "Items": [f"/data/{state}/*"]},
                           "CallerReference": f"static-{time.time_ns()}"},
    )  # fmt: skip
    return response["Invalidation"]["Id"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count what would change")
    parser.add_argument("--out", type=Path, help="also write the files to this folder")
    args = parser.parse_args()
    bucket = os.environ.get("SITE_BUCKET")
    if not bucket and not args.out:
        raise SystemExit(
            "Set SITE_BUCKET (terraform -chdir=infra/main output site_bucket), or --out"
        )
    started = time.time()
    with duckdb.connect(WAREHOUSE, read_only=True) as conn:
        counts = sync(build(conn), bucket, out=args.out, dry_run=args.dry_run)
    verb = "would upload" if args.dry_run else "uploaded"
    print(f"{counts['files']:,} files ({counts['bytes'] / 1e6:,.0f} MB compressed); "
          f"{verb} {counts['put']:,}, deleted {counts['deleted']:,}, "
          f"in {time.time() - started:.0f}s")  # fmt: skip
    distribution = os.environ.get("SITE_DISTRIBUTION_ID")
    if distribution and (counts["put"] or counts["deleted"]) and not args.dry_run:
        print(f"cleared /data/{STATE}/* from the site cache ({invalidate(distribution)})")


if __name__ == "__main__":
    main()
