"""The monthly runner: file listing, the pointer, and resuming from DynamoDB status.

Runs the real parser and normalizer on the insurer fixture, in threads instead of processes
so the patched paths apply, with a fake DynamoDB table."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ingest.insurers import run

FIXTURE = Path("tests/fixtures/insurers/2026-10-01_fixture-insurer_fixture-network_in-network-rates.json.gz")  # fmt: skip


class FakeTable:
    """put_item and query (by PK, paged two items at a time) over a dict."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[(Item["PK"], Item["SK"])] = Item

    def query(self, KeyConditionExpression, ExpressionAttributeValues, ExclusiveStartKey=None):
        pk = ExpressionAttributeValues[":pk"]
        keys = sorted(k for k in self.items if k[0] == pk)
        start = keys.index(ExclusiveStartKey) + 1 if ExclusiveStartKey else 0
        page = {"Items": [self.items[k] for k in keys[start : start + 2]]}
        if start + 2 < len(keys):
            page["LastEvaluatedKey"] = keys[start + 1]
        return page


def toc(*locations):
    return {"reporting_structure": [{"in_network_files": [{"location": loc} for loc in locations]}]}


def test_all_in_network_files_dedupes_filters_and_sorts():
    t = toc("https://x/b_net-b_in-network-rates.json.gz?sig=1",
            "https://x/a_net-a_in-network-rates.json.gz?sig=2",
            "https://x/b_net-b_in-network-rates.json.gz?sig=3")  # fmt: skip
    assert list(run.all_in_network_files(t)) == [
        "a_net-a_in-network-rates.json.gz",
        "b_net-b_in-network-rates.json.gz",
    ]
    assert run.all_in_network_files(t)["b_net-b_in-network-rates.json.gz"].endswith("sig=1")
    assert list(run.all_in_network_files(t, ["net-a"])) == ["a_net-a_in-network-rates.json.gz"]


def test_toc_from_pointer():
    pointer = {"mrfs": [
        {"program": "other", "kind": "TOC", "files": [{"url": "wrong"}]},
        {"program": "cost_transparency", "kind": "TOC", "files": [{"url": "https://toc"}],
         "extra_fields": {"reporting_month": "2026-10"}},
    ]}  # fmt: skip
    assert run.toc_from_pointer(pointer) == ("https://toc", "2026-10")
    with pytest.raises(ValueError):
        run.toc_from_pointer({"mrfs": []})


def test_to_dynamo_converts_floats_and_drops_nones():
    assert run.to_dynamo({"a": 1.5, "b": None, "c": [2.0], "d": "x"}) == {
        "a": run.Decimal("1.5"), "c": [run.Decimal("2.0")], "d": "x"}  # fmt: skip


def test_status_pages_through_query_results():
    table = FakeTable()
    status = run.Status("cigna", "2026-10", table=table)
    for i in range(5):
        status.file(f"f{i}", "done")
    status.put("SUMMARY#2026-10-17T19:13:42+00:00", files=5)
    assert sorted(status.all()) == [f"f{i}" for i in range(5)]


@pytest.fixture
def runner(monkeypatch, tmp_path):
    """Runs against the fixture plus a missing file, sharing one fake status table.
    Returns (go, statuses, table)."""
    missing = (tmp_path / "2026-10-01_fixture-insurer_gone_in-network-rates.json.gz").as_posix()
    monkeypatch.setattr(run, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(run, "current_toc", lambda insurer: ("toc", "2026-10"))
    monkeypatch.setattr(run, "load_toc", lambda url: toc(FIXTURE.as_posix(), missing))
    monkeypatch.setattr("ingest.insurers.tic.RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(run, "PARQUET_DIR", tmp_path / "parquet")
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    monkeypatch.setenv("TASK_VCPU", "4")
    monkeypatch.setenv("TASK_MEMORY_GB", "8")
    table = FakeTable()

    def go(skip_failed=False):
        return run.run("cigna", None, 1, skip_failed, table=table)

    def statuses():
        return {sk: i["status"] for (_, sk), i in table.items.items() if sk.startswith("FILE#")}

    return go, statuses, table


def test_a_run_records_each_file_and_a_summary(runner):
    go, statuses, table = runner
    summary = go()
    good = f"FILE#{FIXTURE.name}"
    assert statuses() == {good: "done", "FILE#2026-10-01_fixture-insurer_gone_in-network-rates.json.gz": "failed"}  # fmt: skip
    item = table.items[("RUN#cigna#2026-10", good)]
    assert item["rows"] == 8 and item["hospitals"] == 2 and item["kept_groups"] == 2
    assert summary["files"] == 2 and summary["done_total"] == 1 and summary["failed_total"] == 1
    assert summary["rows"] == 8  # revenue and unpriced codes are dropped later, in dbt
    assert summary["estimated_cost_usd"] is not None


def test_a_rerun_skips_done_files_and_retries_failed_ones(runner):
    go, _, _ = runner
    go()
    second = go()
    assert second["done_this_run"] == 0 and second["failed_this_run"] == 1
    third = go(skip_failed=True)
    assert third["done_this_run"] == 0 and third["failed_this_run"] == 0
    assert third["done_total"] == 1 and third["failed_total"] == 1


def test_a_new_npi_list_reruns_done_files(runner, monkeypatch):
    go, _, _ = runner
    go()
    npis = run.hospital_npis()
    monkeypatch.setattr(run, "hospital_npis", lambda: npis | {1234567890: "030011"})
    again = go()
    assert again["done_this_run"] == 1  # the done file, parsed with the old list, runs again


def test_npis_version_ignores_order_and_sees_changes():
    a = run.npis_version({1: "030006", 2: "030011"})
    assert a == run.npis_version({2: "030011", 1: "030006"})
    assert a != run.npis_version({1: "030006", 2: "030012"})
