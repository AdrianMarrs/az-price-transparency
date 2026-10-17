from pathlib import Path

from botocore.exceptions import ClientError

from ingest.storage import download_dir, s3_key, upload


class FakeS3:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def upload_file(self, filename, bucket, key):
        if self.fail:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "PutObject")
        self.calls.append((filename, bucket, key))


def test_keys_mirror_the_local_layout():
    assert s3_key(Path("data/raw/2026-10-16/030006_x.csv.gz")) == "raw/2026-10-16/030006_x.csv.gz"
    assert s3_key(Path("data/parsed/030006.parquet")) == "parquet/030006.parquet"
    insurer = "data/insurers/raw/insurer=cigna/month=2026-10/x.jsonl.gz"
    assert s3_key(Path(insurer)) == "raw/insurer=cigna/month=2026-10/x.jsonl.gz"


def test_nothing_is_uploaded_without_a_bucket(monkeypatch):
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    s3 = FakeS3()
    assert upload(Path("data/parsed/030006.parquet"), s3) is None
    assert s3.calls == []


def test_upload_returns_the_s3_uri(monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    s3 = FakeS3()
    assert upload(Path("data/parsed/030006.parquet"), s3) == "s3://bucket/parquet/030006.parquet"
    assert s3.calls == [
        (str(Path("data/parsed/030006.parquet")), "bucket", "parquet/030006.parquet")
    ]


def test_a_failed_upload_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    assert upload(Path("data/parsed/030006.parquet"), FakeS3(fail=True)) is None


class FakeListingS3:
    """list_objects_v2 pages (one object per page) and download_file over a dict."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        for key in sorted(k for k in self.objects if k.startswith(Prefix)):
            yield {"Contents": [{"Key": key}]}

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[key])


def test_download_dir_mirrors_a_bucket_prefix(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    s3 = FakeListingS3({
        "parquet/insurer=cigna/month=2026-10/arizona-hmo.parquet": b"a",
        "parquet/insurer=cigna/month=2026-10/national-ppo.parquet": b"b",
        "parquet/insurer=cigna/month=2026-11/arizona-hmo.parquet": b"other month",
    })  # fmt: skip
    local = Path("data/insurers/parquet/insurer=cigna/month=2026-10")
    paths = download_dir(local, s3)
    assert sorted(p.name for p in paths) == ["arizona-hmo.parquet", "national-ppo.parquet"]
    assert (local / "national-ppo.parquet").read_bytes() == b"b"
