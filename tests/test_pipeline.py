"""The national pipeline runner and seeds, with a lake in a temporary folder (no network)."""

import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from ingest import lake, pipeline
from ingest.hospitals import compliance, parse
from ingest.hospitals.load import write_hospital
from ingest.national.seeds import merge_sources, national_sources

FIXTURE = Path("tests/fixtures/030006.csv")


@pytest.fixture(autouse=True)
def temp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE", str(tmp_path / "lake"))
    monkeypatch.setattr(parse, "PARSED_DIR", tmp_path / "parsed")
    monkeypatch.setattr(pipeline, "PARSED_DIR", tmp_path / "parsed")
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    (tmp_path / "parsed").mkdir()


def raw_copy(tmp_path) -> Path:
    path = tmp_path / "raw" / "030006_standardcharges.csv.gz"
    path.parent.mkdir(parents=True)
    path.write_bytes(gzip.compress(FIXTURE.read_bytes()))
    return path


def test_a_file_is_parsed_into_the_lake_and_the_local_copies_removed(tmp_path):
    path = raw_copy(tmp_path)
    entry = pipeline.parse_and_load("030006", "AZ", path, 1234, keep=False)
    assert entry["outcome"] in ("parsed", "partly_parsed")
    rows = lake.read("raw/hospital_charges/*/*/*.parquet")
    assert rows.height == int(entry["valid"]) > 0
    assert set(rows["source_file_id"]) == {1234} and set(rows["state"]) == {"AZ"}
    assert not path.exists() and not list((tmp_path / "parsed").iterdir())


def test_keep_leaves_the_local_copies(tmp_path):
    path = raw_copy(tmp_path)
    pipeline.parse_and_load("030006", "AZ", path, 1, keep=True)
    assert path.exists() and (tmp_path / "parsed" / "030006.parquet").exists()


def test_a_hospital_is_skipped_only_when_recent_and_in_the_lake(tmp_path):
    now = datetime(2026, 10, 18, tzinfo=UTC)
    attempts = pl.DataFrame({
        "ccn": ["030006", "030010", "030011", "030036"],
        "outcome": ["downloaded", "downloaded", "failed", "unchanged"],
        "attempted_at": [now - timedelta(days=1), now - timedelta(days=30), now, now],
    })  # fmt: skip
    write_hospital(pl.read_parquet(parse_fixture(tmp_path)), "030006", "AZ")
    loaded = pipeline.loaded_hospitals() | {"030010", "030011"}
    # 030010 too old, 030011 failed, 030036 not in the lake
    assert pipeline.recently_done(attempts, 7, now, loaded) == {"030006"}


def parse_fixture(tmp_path) -> Path:
    _, valid, _ = parse.parse_file(FIXTURE, parse.load_shoppable())
    out = tmp_path / "fixture.parquet"
    valid.with_columns(pl.lit(None, pl.Int64).alias("source_file_id")).write_parquet(out)
    return out


def test_the_lake_parse_reports_override_the_local_one(tmp_path, monkeypatch):
    report = tmp_path / "parse_report.csv"
    pl.DataFrame({"ccn": ["030006", "030010"], "outcome": ["parsed", "failed"]}).write_csv(report)
    monkeypatch.setattr(compliance, "REPORT_PATH", report)
    pipeline.save_reports([{"ccn": "030010", "outcome": "partly_parsed", "valid": 5}])
    pipeline.save_reports([{"ccn": "030010", "outcome": "parsed", "valid": 6}])
    found = compliance.parse_reports()
    assert found["030006"]["outcome"] == "parsed"
    assert (found["030010"]["outcome"], found["030010"]["valid"]) == ("parsed", "6")


def test_hospitals_to_run_are_the_states_in_scope_ones_with_a_file(monkeypatch, tmp_path):
    hospitals = tmp_path / "hospitals.csv"
    sources = tmp_path / "sources.csv"
    pl.DataFrame(
        {
            "ccn": ["030006", "030007", "450001", "450002"],
            "state": ["AZ", "AZ", "TX", "TX"],
            "federally_run": ["false", "true", "false", "false"],
        }
    ).write_csv(hospitals)
    pl.DataFrame({"ccn": ["030006", "030007", "450001", "450002"],
                  "mrf_url": ["https://a/f.csv", "https://b/f.csv", "https://c/f.csv", ""]}
                 ).write_csv(sources)  # fmt: skip
    monkeypatch.setattr(pipeline, "HOSPITALS_PATH", hospitals)
    monkeypatch.setattr(pipeline, "SOURCES_PATH", sources)
    assert pipeline.hospitals_to_run(["az", "TX"])["ccn"].to_list() == ["030006", "450001"]


def test_national_sources_keep_the_curated_rows():
    national = pl.DataFrame({
        "ccn": ["030006", "450001", "450002"], "website": ["https://x.org", "https://t.org", ""],
        "status": ["found", "system_match", "no_website"], "location_name": ["X", "T", ""],
        "mrf_url": ["https://x.org/new.csv", "https://t.org/f.csv", ""],
        "source_page_url": ["", "", ""], "website_source": ["dolthub", "wikidata", None],
    })  # fmt: skip
    curated = pl.DataFrame({
        "ccn": ["030006"], "cms_hpt_url": ["https://x.org/cms-hpt.txt"],
        "status": ["found_manual_copy"], "location_name": ["X"], "source_page_url": [""],
        "mrf_url": ["https://x.org/checked.csv"], "website_source": ["manual"],
        "checked_at": ["2026-10-16T00:00:00Z"],
    })  # fmt: skip
    out = merge_sources(curated, national_sources(national, "2026-10-18T00:00:00Z"))
    assert out["ccn"].to_list() == ["030006", "450001", "450002"]
    assert out.row(0, named=True)["mrf_url"] == "https://x.org/checked.csv"  # hand-checked
    tx = out.row(1, named=True)
    assert (tx["cms_hpt_url"], tx["status"]) == ("https://t.org/cms-hpt.txt", "system_match")
    assert out.row(2, named=True)["status"] == "website_not_found"


def test_a_big_file_is_left_for_later(tmp_path, monkeypatch):
    path = raw_copy(tmp_path)
    row = {"ccn": "030006", "url": "u", "outcome": "downloaded", "path": str(path),
           "size_bytes": 1000}  # fmt: skip
    monkeypatch.setattr(pipeline.download, "download", lambda *a: dict(row))
    monkeypatch.setattr(pipeline, "BIG_BYTES", 1000)  # the fixture's CSV is bigger
    job = pipeline.Job("030006", "AZ", "u", None)
    result = pipeline.process(job, tmp_path, keep=False)
    assert result["big"] and result["entry"] is None and result["row"]["id"] > 0
    assert path.exists()  # parsed later, by run_big


def test_a_small_file_is_parsed_in_the_worker(tmp_path, monkeypatch):
    path = raw_copy(tmp_path)
    row = {"ccn": "030006", "url": "u", "outcome": "downloaded", "path": str(path),
           "size_bytes": 1000}  # fmt: skip
    monkeypatch.setattr(pipeline.download, "download", lambda *a: dict(row))
    result = pipeline.process(pipeline.Job("030006", "AZ", "u", None), tmp_path, keep=False)
    assert not result["big"] and result["entry"]["outcome"] in ("parsed", "partly_parsed")
    assert path.exists()  # no data bucket: the only copy is kept


def test_an_error_fails_only_that_hospital(tmp_path, monkeypatch):
    def broken(*args):
        raise OSError(12, "Cannot allocate memory")

    monkeypatch.setattr(pipeline.download, "download", broken)
    result = pipeline.process(pipeline.Job("030006", "AZ", "u", None), tmp_path, keep=False)
    assert (
        result["row"]["outcome"] == "failed" and "Cannot allocate memory" in result["row"]["error"]
    )


def test_empty_tables_get_a_file_with_their_columns():
    made = pipeline.ensure_tables()
    assert len(made) == 3
    rates = lake.read("raw/insurer_rates/*/*/*/*.parquet")
    assert rates.is_empty() and {"negotiated_rate", "insurer", "network", "loaded_at"} <= set(
        rates.columns
    )
    assert pipeline.ensure_tables() == []  # only once


def test_a_table_with_files_is_left_alone(tmp_path):
    write_hospital(pl.read_parquet(parse_fixture(tmp_path)), "030006", "AZ")
    made = pipeline.ensure_tables()
    assert not any("hospital_charges" in m for m in made)


def test_a_hospital_over_the_time_limit_is_stopped_and_the_rest_go_on(tmp_path, monkeypatch):
    import threading
    import time as time_
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    body = FIXTURE.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.end_headers()
            if self.path.startswith("/slow"):
                for _ in range(600):  # a trickle: never idle long enough for a read timeout
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time_.sleep(0.1)
            else:
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    todo = pl.DataFrame({"ccn": ["999990", "999991"], "state": ["AZ", "AZ"],
                         "mrf_url": [f"{base}/slow.csv", f"{base}/fast.csv"]})  # fmt: skip
    monkeypatch.setattr(pipeline, "hospitals_to_run", lambda states: todo)
    monkeypatch.setattr(pipeline, "JOB_LIMIT_SECONDS", 5)
    monkeypatch.setattr(pipeline, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setenv("BROWSER_FALLBACK", "0")
    try:
        rows = {r["ccn"]: r for r in pipeline.run_hospitals(["AZ"], 2, None, 7, keep=True)}
    finally:
        server.shutdown()
        for leftover in Path("data/parsed").glob("99999*"):  # the workers' (made-up CCNs)
            leftover.unlink()
    assert rows["999990"]["outcome"] == "failed" and "not done after" in rows["999990"]["error"]
    assert rows["999991"]["outcome"] == "downloaded"


def test_a_zip_is_sized_by_the_file_inside(tmp_path):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("charges.csv", "x" * 5_000_000)  # compresses to a few KB
    path = tmp_path / "030006_charges.zip.gz"
    path.write_bytes(gzip.compress(buffer.getvalue()))
    assert path.stat().st_size < 100_000
    assert parse.content_size(path) == 5_000_000
    assert parse.content_size(raw_copy(tmp_path)) == FIXTURE.stat().st_size
