"""Hospital loader tests: parsed prices written to a lake in a temporary folder."""

from datetime import UTC, datetime
from decimal import Decimal

import polars as pl
import pytest

from ingest import lake
from ingest.hospitals import source_log
from ingest.hospitals.load import COLUMNS, write_hospital

GLOB = "raw/hospital_charges/*/*/*.parquet"


@pytest.fixture(autouse=True)
def temp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE", str(tmp_path / "lake"))


def frame(n: int) -> pl.DataFrame:
    rows = [
        {"source_file_id": 1, "description": f"MRI knee {i}",
         "code": "73721", "code_type": "CPT/HCPCS", "cms_shoppable_id": 33,
         "setting": "outpatient", "billing_class": "facility", "modifiers": None,
         "payer_name": "Aetna, Inc.", "plan_name": 'PPO "Choice"', "methodology": "case rate",
         "price_type": "negotiated_dollar", "amount": Decimal("689.1234"), "algorithm": None}
        for i in range(n)
    ]  # fmt: skip
    return pl.DataFrame(rows, schema_overrides={"amount": pl.Decimal(18, 4)}).select(COLUMNS)


def test_values_and_nulls_round_trip_and_folders_become_columns():
    write_hospital(frame(3), "030006", "AZ")
    row = lake.read(GLOB).row(0, named=True)
    assert (row["payer_name"], row["plan_name"], row["amount"], row["modifiers"]) == (
        "Aetna, Inc.", 'PPO "Choice"', Decimal("689.1234"), None)  # fmt: skip
    # the folder names are text: ccn=030006 is not the number 30006
    assert (row["state"], row["ccn"]) == ("AZ", "030006")
    assert row["loaded_at"].tzinfo is not None


def test_rewriting_a_hospital_replaces_only_its_rows():
    write_hospital(frame(5), "030006", "AZ")
    write_hospital(frame(2), "030064", "AZ")
    write_hospital(frame(2), "320001", "NM")
    write_hospital(frame(3), "030006", "AZ")
    counts = dict(lake.read(GLOB).group_by("ccn").len().rows())
    assert counts == {"030006": 3, "030064": 2, "320001": 2}


def test_an_empty_file_clears_a_hospital():
    write_hospital(frame(5), "030006", "AZ")
    write_hospital(frame(1).clear(), "030006", "AZ")
    assert lake.read(GLOB).height == 0


@pytest.mark.parametrize("ccn,state", [("030006", "az; DROP"), ("../x", "AZ"), ("1", "AZ")])
def test_names_that_are_not_plain_are_refused(ccn, state):
    with pytest.raises(ValueError, match="not a"):
        write_hospital(frame(1), ccn, state)


def test_the_download_log_keeps_every_run_and_finds_the_last_download():
    started = datetime(2026, 10, 1, tzinfo=UTC)
    with source_log.Log() as log:
        first = log.record({"ccn": "030006", "url": "u", "outcome": "downloaded",
                            "sha256": "a", "path": "p1"}, started)  # fmt: skip
        log.record({"ccn": "030006", "url": "u", "outcome": "failed"}, started)  # same instant
        assert log.last("030006", "u").sha256 == "a"  # seen before it's saved
    with source_log.Log() as log:
        log.record({"ccn": "030006", "url": "u", "outcome": "downloaded", "sha256": "b",
                    "path": "p2", "etag": '"v2"'}, started.replace(day=2))  # fmt: skip
    attempts = source_log.read()
    assert attempts.height == 3 and attempts["id"].n_unique() == 3
    assert source_log.Log().last("030006", "u").etag == '"v2"'
    assert source_log.downloaded_id(attempts, "p1") == first
    assert source_log.latest(attempts)["030006"]["sha256"] == "b"


def test_an_empty_log_has_its_columns():
    attempts = source_log.read()
    assert attempts.is_empty() and list(attempts.columns) == list(source_log.SCHEMA)
    assert source_log.Log().last("030006", "u") is None
