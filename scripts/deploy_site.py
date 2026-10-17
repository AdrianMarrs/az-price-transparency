"""Upload the built site (web/build/client) to its bucket and clear its pages from CloudFront.

Usage (after `npm run build` in web/, or the Docker build in docker/web.Dockerfile):
    uv run python scripts/deploy_site.py

Bucket and distribution come from SITE_BUCKET and SITE_DISTRIBUTION_ID, or else from
`terraform -chdir=infra/main output`. Files under assets/ have a content hash in their name,
so they are cached for a year. Pages (.html) and their data (.data) keep their names from
build to build, so browsers revalidate them every time and the deploy clears them from
CloudFront. Files no longer in the build are deleted.
"""

import json
import mimetypes
import os
import subprocess
import time
from pathlib import Path

import boto3

DIST = Path("web/build/client")
IMMUTABLE = "public, max-age=31536000, immutable"


def terraform_outputs() -> dict:
    out = subprocess.run(
        ["terraform", "-chdir=infra/main", "output", "-json"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return {k: v["value"] for k, v in json.loads(out).items()}


def cache_control(key: str) -> str:
    return IMMUTABLE if key.startswith("assets/") else "no-cache"


def content_type(key: str) -> str:
    if key.endswith(".data"):  # a pre-rendered page's loader data, as React Router serves it
        return "text/x-script"
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


def main() -> None:
    if not (DIST / "index.html").exists():
        raise SystemExit(f"no {DIST.as_posix()}/index.html: run `npm run build` in web/ first")
    bucket = os.environ.get("SITE_BUCKET")
    distribution = os.environ.get("SITE_DISTRIBUTION_ID")
    if not (bucket and distribution):
        outputs = terraform_outputs()
        bucket, distribution = outputs["site_bucket"], outputs["site_distribution_id"]

    s3 = boto3.client("s3")
    keys = []
    # Pages last, so a page never points at assets that aren't uploaded yet.
    files = sorted((p for p in DIST.rglob("*") if p.is_file()), key=lambda p: p.suffix == ".html")
    for path in files:
        key = path.relative_to(DIST).as_posix()
        s3.upload_file(str(path), bucket, key, ExtraArgs={
            "ContentType": content_type(key), "CacheControl": cache_control(key)})  # fmt: skip
        keys.append(key)
    stale = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket)
             for o in page.get("Contents", []) if o["Key"] not in keys]  # fmt: skip
    for i in range(0, len(stale), 1000):
        s3.delete_objects(
            Bucket=bucket, Delete={"Objects": [{"Key": k} for k in stale[i : i + 1000]]}
        )
    boto3.client("cloudfront").create_invalidation(
        DistributionId=distribution,
        InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]},  # one path, however many files
                           "CallerReference": f"deploy-{time.time_ns()}"},
    )  # fmt: skip
    print(f"uploaded {len(keys)} files to s3://{bucket}, deleted {len(stale)}, cleared CloudFront")


if __name__ == "__main__":
    main()
