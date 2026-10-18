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

Reads the dbt serving models (serving.srv_hospital_service_items and srv_hospital_profiles)
and marts.dim_services. Needs SITE_BUCKET; with SITE_DISTRIBUTION_ID set and anything
changed, it clears /data/* from the site's CloudFront cache.
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
import psycopg

from serving.export_dynamodb import DATABASE_URL, compact, services_list

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


def profiles(conn: psycopg.Connection) -> dict[str, dict]:
    rows = conn.execute("SELECT item FROM serving.srv_hospital_profiles").fetchall()
    found = {}
    for (item,) in rows:
        p = compact(json.loads(item))
        found[p["ccn"]] = p
    return found


def service_items(conn: psycopg.Connection) -> Iterator[tuple[str, list[dict]]]:
    """(service key, every hospital's item for it), streamed one service at a time."""
    sql = """SELECT gsi1pk, item FROM serving.srv_hospital_service_items
             ORDER BY gsi1pk, item_key"""
    key, items = None, []
    with conn.transaction(), conn.cursor(name="service_items") as cur:
        cur.itersize = 2000
        cur.execute(sql)
        for gsi1pk, item in cur:
            this = gsi1pk.removeprefix("SERVICE#")
            if key is not None and this != key:
                yield key, items
                items = []
            key = this
            items.append(compact(json.loads(item)))
    if key is not None:
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


def build(conn: psycopg.Connection, state: str = STATE) -> Iterator[tuple[str, bytes]]:
    """(S3 key, gzip bytes) for every file."""
    prefix = f"data/{state}"
    services = services_list(conn)
    yield f"{prefix}/search.json", encode(services)
    hospitals = profiles(conn)
    for ccn, p in hospitals.items():
        yield f"{prefix}/providers/{ccn}.json", encode(p | {"note": NOTE})
    by_key = {s["key"]: s for s in services}
    for key, items in service_items(conn):
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
    with psycopg.connect(DATABASE_URL) as conn:
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
