"""Insurer loader tests: networks written to a lake in a temporary folder."""

import polars as pl
import pytest

from ingest import lake
from ingest.insurers.load import load_network
from ingest.insurers.normalize import SCHEMA as COLUMNS

GLOB = "raw/insurer_rates/*/*/*/*.parquet"


@pytest.fixture(autouse=True)
def temp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE", str(tmp_path / "lake"))


def frame(network: str, n: int, month: str = "2026-10") -> pl.DataFrame:
    rows = [
        {"insurer": "cigna", "network": network, "month": month, "ccn": "030006",
         "billing_code_type": "CPT", "billing_code": "73721", "description": "MRI knee",
         "negotiation_arrangement": "ffs", "negotiated_type": "negotiated",
         "negotiated_rate": 100.0 + i, "billing_class": "institutional", "setting": "outpatient",
         "service_codes": "11,22" if i else None, "modifiers": None, "expiration_date": "9999-12-31"}
        for i in range(n)
    ]  # fmt: skip
    return pl.DataFrame(rows, schema=COLUMNS)


def counts() -> dict:
    df = lake.read(GLOB)
    return dict(df.group_by(pl.format("{}/{}", "network", "month")).len().rows())


def test_values_and_nulls_round_trip():
    assert load_network(frame("arizona-hmo", 2)) == 2
    rows = lake.read(GLOB).sort("negotiated_rate")
    assert rows.select("negotiated_rate", "service_codes").rows() == [(100.0, None),
                                                                        (101.0, "11,22")]  # fmt: skip
    assert rows["ccn"][0] == "030006"


def test_reloading_a_network_replaces_only_its_rows():
    load_network(frame("arizona-hmo", 5))
    load_network(frame("phoenix-az-connect", 2))
    load_network(frame("arizona-hmo", 4, month="2026-11"))
    load_network(frame("arizona-hmo", 3))
    assert counts() == {
        "arizona-hmo/2026-10": 3,
        "arizona-hmo/2026-11": 4,
        "phoenix-az-connect/2026-10": 2,
    }


def test_a_frame_must_be_one_network():
    mixed = pl.concat([frame("arizona-hmo", 1), frame("phoenix-az-connect", 1)])
    with pytest.raises(ValueError):
        load_network(mixed)


def test_a_network_name_must_be_plain():
    with pytest.raises(ValueError, match="plain name"):
        load_network(frame("../elsewhere", 1))


def test_an_empty_frame_loads_nothing():
    assert load_network(pl.DataFrame(schema=COLUMNS)) == 0
