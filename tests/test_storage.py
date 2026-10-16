from pathlib import Path

from botocore.exceptions import ClientError

from ingest.storage import s3_key, upload


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
