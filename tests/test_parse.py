import csv
import gzip
import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from ingest.hospitals.parse import (
    OUTPUT_COLUMNS,
    PriceRow,
    load_shoppable,
    match_codes,
    normalize_header,
    outcome,
    parse_date,
    parse_file,
    parse_one,
    pydantic_reason,
    read_csv_items,
    read_csv_with_python,
    read_json,
    sniff_format,
    to_long,
    validate,
)

FIXTURES = Path(__file__).parent / "fixtures"
SHOPPABLE = load_shoppable()


# ---------- headers, dates, codes ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("description ", "description"),
        ("code |1", "code|1"),
        ("code|1|Type", "code|1|type"),
        ("standard_charge | gross", "standard_charge|gross"),
        (
            "standard_charge|[payer_AETNA ]|[plan_ HMO/PPO]|negotiated_dollar",
            "standard_charge|AETNA|HMO/PPO|negotiated_dollar",
        ),
        ("median_amount|Aetna|Aetna ALL", "median_amount|Aetna|Aetna ALL"),
        ("﻿hospital_name", "hospital_name"),
    ],
)
def test_normalize_header(raw, expected):
    assert normalize_header(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-04-30", date(2026, 4, 30)),
        ("    2026-04-01", date(2026, 4, 1)),
        ("7/31/2026", date(2026, 7, 31)),
        ("12/31/2025", date(2025, 12, 31)),
        ("April 1", None),
        ("", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_match_codes_keeps_service_codes_and_flags_the_cms_70():
    items = pl.DataFrame(
        {
            "code|1": ["1010014", "73721", "470", "73722", "G0121", "J1885", "A4550", "8"],
            "code|1|type": ["CDM", "hcpcs", "MS DRG", "CPT", "HCPCS", "HCPCS", "HCPCS",
                            "MS-DRG"],
            "code|2": ["73721", None, None, None, None, None, None, None],
            "code|2|type": ["CPT", None, None, None, None, None, None, None],
        }
    ).with_row_index("row_idx")  # fmt: skip
    matched = match_codes(items, SHOPPABLE).sort("row_idx")
    assert matched.select("row_idx", "code", "code_type", "cms_shoppable_id").rows() == [
        (0, "73721", "CPT/HCPCS", 33),  # CDM line carrying a CPT in its second code
        (1, "73721", "CPT/HCPCS", 33),
        (2, "470", "MS-DRG", 43),  # padded DRG, in the 70
        (3, "73722", "CPT/HCPCS", None),  # a service, not in the 70
        (4, "G0121", "CPT/HCPCS", None),  # HCPCS G code: a service
        (7, "008", "MS-DRG", None),  # J (drug) and A (supply) codes are dropped
    ]


# ---------- validation ----------

BASE = {
    "description": "MRI knee",
    "code": "73721",
    "code_type": "CPT/HCPCS",
    "cms_shoppable_id": 33,
    "setting": "outpatient",
    "price_type": "gross",
    "amount": "100",
}


def test_price_row_cleans_amounts_case_and_whitespace():
    row = PriceRow(**{**BASE, "amount": "$1,234.50", "setting": "Outpatient\r\n",
                      "description": " MRI   knee "})  # fmt: skip
    assert row.amount == Decimal("1234.50")
    assert row.setting == "outpatient"
    assert row.description == "MRI knee"


def test_price_row_lowercases_methodology():
    row = PriceRow(**{**BASE, "price_type": "negotiated_dollar", "payer_name": "Aetna",
                      "methodology": "Per diem"})  # fmt: skip
    assert row.methodology == "per diem"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"amount": "-5"}, "negative amount"),
        ({"amount": "N/A"}, "not a number"),
        ({"amount": None}, "missing amount"),
        ({"price_type": "negotiated_dollar"}, "without a payer"),
        ({"price_type": "negotiated_algorithm", "payer_name": "Aetna", "amount": None},
         "without algorithm text"),
        ({"setting": "emergency"}, "setting"),
        ({"price_type": "negotiated_dollar", "payer_name": "X", "methodology": "capitation"},
         "methodology"),
    ],
)  # fmt: skip
def test_price_row_rejects_with_a_reason(changes, message):
    with pytest.raises(ValidationError, match=message):
        PriceRow(**{**BASE, **changes})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({}, ""),
        ({"amount": "$1,234.50", "setting": "Outpatient\r\n"}, ""),
        ({"amount": "-5"}, "negative amount"),
        ({"amount": "N/A"}, "not a number"),
        ({"amount": None}, "missing amount"),
        ({"price_type": "negotiated_dollar"}, "without a payer"),
        ({"setting": "emergency"}, "setting"),
    ],
)
def test_bulk_validation_gives_the_same_verdict_as_pydantic(changes, message):
    row = {c: None for c in OUTPUT_COLUMNS} | BASE | changes
    frame = pl.DataFrame([row], schema={c: pl.String for c in OUTPUT_COLUMNS}
                         | {"cms_shoppable_id": pl.Int64})  # fmt: skip
    valid, rejects = validate(frame)
    if message:
        assert rejects.height == 1 and message in rejects["reason"][0]
        assert pydantic_reason(row) is not None
    else:
        assert valid.height == 1 and valid["amount"][0] == Decimal(
            row["amount"].strip("$").replace(",", "")
        )
        assert pydantic_reason(row) is None


# ---------- real-file fixtures (tests/fixtures, cut by scripts/make_fixtures.py) ----------

FIXTURE_FILES = sorted(FIXTURES.glob("*.*"))
SHAPES = {"030006": "tall", "030010": "json", "030011": "json", "030064": "tall",
          "030085": "wide", "030111": "tall", "030114": "wide", "030148": "wide",
          "034022": "wide", "034030": "tall", "034033": "wide",
          # statewide: CommonSpirit JSON, Havasu (zip), Kingman (needs the csv fallback at
          # full size), Phoenix Children's (no file extension in its URL)
          "030036": "json", "030069": "tall", "030055": "tall", "033302": "tall"}  # fmt: skip


@pytest.fixture(scope="module", params=FIXTURE_FILES, ids=lambda p: p.stem)
def parsed(request):
    meta, valid, rejects = parse_file(request.param, SHOPPABLE)
    return request.param.stem, meta, valid, rejects


def test_every_fixture_parses_with_its_shape_and_version(parsed):
    ccn, meta, _, _ = parsed
    assert meta["shape"] == SHAPES[ccn]
    assert meta["version"] == "3.0.0"
    assert isinstance(meta["last_updated_on"], date)


def test_valid_rows_are_services_and_normalized(parsed):
    _, _, valid, _ = parsed
    if valid.is_empty():
        return
    drg = pl.col("code_type") == "MS-DRG"
    assert valid.filter(drg)["code"].str.contains(r"^\d{3}$").all()
    assert valid.filter(~drg)["code"].str.contains(r"^(\d{5}|G\d{4})$").all()
    flagged = valid.filter(pl.col("cms_shoppable_id").is_not_null())
    shoppable = set(SHOPPABLE.select("code", "code_type").iter_rows())
    assert set(flagged.select("code", "code_type").iter_rows()) <= shoppable
    assert set(valid["setting"]) <= {"inpatient", "outpatient", "both"}
    assert valid.height == valid.unique().height
    negotiated = valid.filter(pl.col("price_type").str.starts_with("negotiated"))
    assert negotiated["payer_name"].null_count() == 0


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.stem)
def test_bulk_validation_agrees_with_pydantic_on_real_rows(path):
    items = read_json(path)[1] if path.suffix == ".json" else read_csv_items(path)
    long = to_long(items, SHOPPABLE).unique()
    valid, _ = validate(long)
    accepted_in_bulk = valid.height
    accepted_by_pydantic = sum(pydantic_reason(r) is None for r in long.iter_rows(named=True))
    assert accepted_in_bulk == accepted_by_pydantic


def test_rejects_always_carry_a_reason(parsed):
    _, _, _, rejects = parsed
    assert rejects["reason"].null_count() == 0


def test_fixtures_with_insurer_prices_produce_them(parsed):
    ccn, _, valid, _ = parsed
    if ccn in {"030006", "030064", "030085", "030111", "030114", "030148", "034033"}:
        assert valid.filter(pl.col("price_type").str.starts_with("negotiated")).height > 0


def test_format_is_sniffed_from_content_not_name(tmp_path):
    csv_gz, json_gz, zip_gz = tmp_path / "a.gz", tmp_path / "b.gz", tmp_path / "c.gz"
    csv_gz.write_bytes(gzip.compress(b"\xef\xbb\xbfhospital_name,version\n"))
    json_gz.write_bytes(gzip.compress(b'  {"hospital_name": "x"}'))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("prices.csv", "hospital_name\n")
    zip_gz.write_bytes(gzip.compress(buffer.getvalue()))
    assert [sniff_format(p) for p in (csv_gz, json_gz, zip_gz)] == ["csv", "json", "zip"]


def test_zip_files_are_parsed_through_their_csv(tmp_path, monkeypatch):
    monkeypatch.setattr("ingest.hospitals.parse.PARSED_DIR", tmp_path)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("readme.txt", "ignore me")
        z.writestr("030006_standardcharges.csv", (FIXTURES / "030006.csv").read_bytes())
    path = tmp_path / "030006_file.zip.gz"
    path.write_bytes(gzip.compress(buffer.getvalue()))
    meta, valid, _ = parse_file(path, SHOPPABLE)
    assert meta["shape"] == "tall" and valid.height > 0
    assert not list((tmp_path / "tmp").iterdir())  # the extracted copy is cleaned up


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({"valid": 100, "rejected": 0}, "parsed"),
        ({"valid": 100, "rejected": 4}, "parsed"),
        ({"valid": 100, "rejected": 10}, "partly_parsed"),
        ({"valid": 0, "rejected": 7}, "all_rejected"),
        ({"valid": 0, "rejected": 0}, "no_service_codes"),
    ],
)
def test_outcome(counts, expected):
    assert outcome(counts) == expected


def test_a_broken_file_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr("ingest.hospitals.parse.PARSED_DIR", tmp_path)
    path = tmp_path / "999999_broken.json.gz"
    path.write_bytes(gzip.compress(b'{"standard_charge_information": [ not json'))
    entry = parse_one("999999", path, SHOPPABLE)
    assert entry["outcome"] == "failed" and "JSONDecodeError" in entry["error"]


def test_files_too_big_for_memory_are_deferred(tmp_path, monkeypatch):
    monkeypatch.setattr("ingest.hospitals.parse.MAX_CSV_BYTES", 10)
    path = tmp_path / "030103_big.csv.gz"
    path.write_bytes(gzip.compress(b"hospital_name,version\n" * 10))
    assert parse_one("030103", path, SHOPPABLE)["outcome"] == "deferred_too_large"


def test_file_level_payer_counts_include_codes_we_drop():
    # Sonora bills by revenue code, so none of its prices survive the service-code filter,
    # but its file does publish insurer prices.
    meta, valid, _ = parse_file(FIXTURES / "034022.csv", SHOPPABLE)
    assert valid.height == 0
    assert meta["file_payer_prices"] > 0
    assert meta["file_payer_dollar"] <= meta["file_payer_prices"]


def test_tmc_bundled_rows_are_counted_at_file_level():
    meta, _, _ = parse_file(FIXTURES / "030006.csv", SHOPPABLE)
    assert meta["file_payer_bundled"] > 0


@pytest.mark.parametrize("ccn", ["030006", "030085", "034030"])
def test_python_csv_fallback_reads_the_same_as_polars(ccn):
    path = FIXTURES / f"{ccn}.csv"
    fast = pl.read_csv(path, skip_rows=2, infer_schema_length=0, truncate_ragged_lines=True)
    slow = read_csv_with_python(path)
    assert slow.height == fast.height
    assert slow.select(fast.columns[:20]).equals(fast.select(fast.columns[:20]))


def test_rows_that_only_match_after_cleaning_are_deduplicated(tmp_path):
    # Valley View's file lists the same price as "536.13" and "536.130".
    header = ["description", "code|1", "code|1|type", "setting", "standard_charge|min"]
    rows = [
        ["hospital_name", "last_updated_on", "version"],
        ["Test Hospital", "2026-01-01", "3.0.0"],
        header,
        ["3D radiotherapy plan", "77295", "CPT", "outpatient", "536.13"],
        ["3D radiotherapy plan ", "77295", "CPT", "outpatient", "536.130"],
    ]
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    path = tmp_path / "999999_twins.csv"
    path.write_text(buffer.getvalue(), encoding="utf-8")
    meta, valid, _ = parse_file(path, SHOPPABLE)
    assert valid.height == 1
    assert meta["duplicates"] == 1


def test_carondelet_has_no_insurer_prices():
    for ccn in ("030010", "030011"):
        _, valid, _ = parse_file(FIXTURES / f"{ccn}.json", SHOPPABLE)
        assert valid.height > 0
        assert set(valid["price_type"]) <= {"gross", "discounted_cash", "min", "max"}


def test_sonora_payer_names_are_unwrapped():
    # The wrapped headers become plain payer names; the fixture's sample has no shoppable
    # codes, so check the normalized header names directly.
    from ingest.hospitals.parse import read_csv_items

    columns = read_csv_items(FIXTURES / "034022.csv").columns
    assert "standard_charge|AETNA|HMO/PPO|negotiated_dollar" in columns
    assert not any("[payer_" in c for c in columns)


def test_tmc_bundled_items_are_kept_as_algorithm_prices():
    _, valid, _ = parse_file(FIXTURES / "030006.csv", SHOPPABLE)
    bundled = valid.filter(pl.col("algorithm").str.contains("bundled"))
    assert bundled.height > 0
    assert set(bundled["price_type"]) == {"negotiated_algorithm"}
    assert bundled["amount"].null_count() == bundled.height
