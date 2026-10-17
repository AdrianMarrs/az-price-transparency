"""Copies of pipeline files in S3, when DATA_BUCKET is set.

Local disk stays the working copy (the parser and loader read it); the bucket is the
durable copy that the cloud pipeline will read. Keys mirror the local layout:

    data/raw/<yyyy-mm-dd>/<file>.gz  ->  raw/<yyyy-mm-dd>/<file>.gz   (expires after 7 days)
    data/parsed/<ccn>.parquet        ->  parquet/<ccn>.parquet
    data/insurers/raw/insurer=<name>/month=<m>/...      ->  raw/insurer=<name>/month=<m>/...
    data/insurers/parquet/insurer=<name>/month=<m>/...  ->  parquet/insurer=<name>/month=<m>/...

Without DATA_BUCKET (tests, CI, a laptop with no AWS login) nothing is uploaded. An upload
that fails is reported and returns None; it never fails the download or parse itself.
"""

import os
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

PREFIXES = {"raw": "raw", "parsed": "parquet"}


def s3_key(path: Path) -> str:
    """The bucket key for a file under data/raw/ or data/parsed/."""
    parts = Path(path).as_posix().split("/")
    i = parts.index("data")
    if parts[i + 1] == "insurers":  # already laid out as raw/... or parquet/...
        return "/".join(parts[i + 2 :])
    return "/".join([PREFIXES[parts[i + 1]], *parts[i + 2 :]])


def upload(path: Path, client=None) -> str | None:
    """Copy path to the data bucket; returns its s3:// URI, or None if not uploaded."""
    bucket = os.environ.get("DATA_BUCKET")
    if not bucket:
        return None
    key = s3_key(path)
    try:
        (client or boto3.client("s3")).upload_file(str(path), bucket, key)
    except (BotoCoreError, ClientError) as e:
        print(f"S3 upload failed for {path}: {e}")
        return None
    return f"s3://{bucket}/{key}"


def download_dir(local_dir: Path, client=None) -> list[Path]:
    """Copy every object under local_dir's bucket prefix into local_dir (the reverse of
    upload), e.g. a month of insurer Parquet written by the cloud run. Returns the paths."""
    bucket = os.environ.get("DATA_BUCKET")
    if not bucket:
        raise RuntimeError("DATA_BUCKET is not set")
    client = client or boto3.client("s3")
    prefix = s3_key(Path(local_dir) / "x").removesuffix("x")
    paths = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            dest = Path(local_dir) / obj["Key"].removeprefix(prefix)
            dest.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, obj["Key"], str(dest))
            paths.append(dest)
    return paths
