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


def warehouse():
    """A tiny warehouse with an Arizona and a New Mexico hospital pricing one knee MRI."""
    import duckdb

    con = duckdb.connect()
    con.execute("CREATE SCHEMA marts; CREATE SCHEMA serving")
    con.execute("""CREATE TABLE marts.dim_services AS SELECT 'cpt-hcpcs:73721' AS service_key,
        '73721' AS code, 'CPT/HCPCS' AS code_type, 'MRI knee' AS common_description,
        33 AS cms_shoppable_id, 'MRI of a joint' AS cms_description, 2 AS hospitals""")
    con.execute(f"CREATE TABLE serving.srv_service_prices AS SELECT * FROM (VALUES "
                "('AZ', 'cpt-hcpcs:73721', '030006', 'Aetna', 'PPO', 'Aetna', 'commercial', "
                " 'outpatient', 'negotiated_dollar', 'fee schedule', 689.5::double, NULL, false, 2),"
                "('AZ', 'cpt-hcpcs:73721', '030006', NULL, NULL, NULL, NULL, "
                " 'outpatient', 'discounted_cash', NULL, 400.0::double, NULL, false, 1),"
                "('NM', 'cpt-hcpcs:73721', '320001', NULL, NULL, NULL, NULL, "
                " 'outpatient', 'gross', NULL, 2000.0::double, NULL, false, 1)"
                f") AS t(state, {', '.join(es.PRICE_COLUMNS)})")  # fmt: skip
    con.execute("""CREATE TABLE serving.srv_hospital_profiles AS SELECT * FROM (VALUES
        ('AZ', '{"ccn": "030006", "name": "TMC", "score_pct": 90}'),
        ('NM', '{"ccn": "320001", "name": "UNM", "score_pct": 50}')) AS t(state, item)""")
    return con


def test_a_state_gets_only_its_own_hospitals():
    files = {k: json.loads(gzip.decompress(b)) for k, b in es.build(warehouse(), "az")}
    assert sorted(files) == ["data/az/providers/030006.json", "data/az/search.json",
                             "data/az/services/cpt-73721.json"]  # fmt: skip
    assert files["data/az/search.json"][0]["hospitals"] == 1  # not New Mexico's too
    (hospital,) = files["data/az/services/cpt-73721.json"]["hospitals"]
    assert hospital["hospital"] == {"ccn": "030006", "name": "TMC", "score_pct": 90}
    assert hospital["plans"] == 1
    assert hospital["standard"] == [{"setting": "outpatient", "type": "discounted_cash",
                                     "amount": 400, "n": 1}]  # fmt: skip
    assert hospital["prices"][0]["amount"] == 689.5
    nm = dict(es.build(warehouse(), "nm"))
    assert "data/nm/providers/320001.json" in nm and "data/nm/providers/030006.json" not in nm
