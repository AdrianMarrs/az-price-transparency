import gzip
import hashlib
import json

from serving import export_static as es


class FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = dict(objects)
        self.puts, self.deletes = [], []

    def get_paginator(self, name):
        s3 = self

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k, "ETag": f'"{hashlib.md5(b).hexdigest()}"'}
                                    for k, b in s3.objects.items() if k.startswith(Prefix)]}  # fmt: skip

        return Paginator()

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.puts.append((Key, kwargs))
        self.objects[Key] = Body

    def delete_objects(self, Bucket, Delete):
        for o in Delete["Objects"]:
            self.deletes.append(o["Key"])
            self.objects.pop(o["Key"])


def test_slug_matches_the_site():
    assert es.slug("cpt-hcpcs:73721") == "cpt-73721"
    assert es.slug("ms-drg:470") == "drg-470"


def test_encoding_is_deterministic_gzip_json():
    value = {"x": [1, "é"]}
    assert es.encode(value) == es.encode(value)
    assert json.loads(gzip.decompress(es.encode(value))) == value


def test_only_changed_files_are_uploaded_and_removed_ones_deleted():
    same, old = es.encode({"same": 1}), es.encode({"v": 1})
    s3 = FakeS3({"data/az/search.json": same, "data/az/services/cpt-1.json": old,
                 "data/az/services/cpt-gone.json": old, "index.html": b"<html>"})  # fmt: skip
    files = [("data/az/search.json", same), ("data/az/services/cpt-1.json", es.encode({"v": 2})),
             ("data/az/providers/030006.json", es.encode({"ccn": "030006"}))]  # fmt: skip
    counts = es.sync(files, "bucket", client=s3)
    assert sorted(k for k, _ in s3.puts) == ["data/az/providers/030006.json",
                                             "data/az/services/cpt-1.json"]  # fmt: skip
    assert s3.puts[0][1] == {"ContentType": "application/json", "ContentEncoding": "gzip",
                             "CacheControl": es.CACHE_CONTROL}  # fmt: skip
    assert s3.deletes == ["data/az/services/cpt-gone.json"]  # never the site's own files
    assert counts == {"files": 3, "bytes": sum(len(b) for _, b in files), "put": 2, "deleted": 1}
    assert es.sync(files, "bucket", client=s3)["put"] == 0  # a rerun uploads nothing


def test_dry_run_changes_nothing():
    s3 = FakeS3({"data/az/services/cpt-gone.json": b"x"})
    counts = es.sync([("data/az/search.json", es.encode([]))], "bucket", client=s3, dry_run=True)
    assert (counts["put"], counts["deleted"]) == (1, 1)
    assert s3.puts == [] and s3.deletes == []


def test_a_service_file_matches_what_the_api_returned():
    service = {"id": "cpt-hcpcs:45378", "key": "CPT/HCPCS:45378"}
    items = [{"ccn": "030014", "plans": 13, "standard": [], "prices": [{"amount": 1432}]},
             {"ccn": "030006", "plans": 3}]  # fmt: skip
    hospitals = {"030014": {"ccn": "030014", "name": "JOHN C. LINCOLN", "score_pct": 82,
                            "mrf_url": "https://x"},
                 "030006": {"ccn": "030006", "name": "TUCSON MEDICAL CENTER"}}  # fmt: skip
    out = es.compare(service, items, hospitals)
    names = [r["hospital"]["name"] for r in out["hospitals"]]
    assert names == ["JOHN C. LINCOLN", "TUCSON MEDICAL CENTER"]
    assert out["hospitals"][0]["hospital"] == {"ccn": "030014", "name": "JOHN C. LINCOLN",
                                               "score_pct": 82}  # fmt: skip
    assert out["hospitals"][1] == {"hospital": {"ccn": "030006", "name": "TUCSON MEDICAL CENTER"},
                                   "plans": 3, "standard": [], "prices": []}  # fmt: skip
    assert out["note"] == es.NOTE
