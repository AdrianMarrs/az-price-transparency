import httpx

from ingest.hospitals.find_sources import MANUAL_DIR, fetch_status, match_location, source_row

SYSTEM_FILE = """location-name: Banner University Medical Center Tucson
source-page-url: https://example.org/prices
mrf-url: https://example.org/tucson_standardcharges.csv

location-name: Banner University Medical Center South
source-page-url: https://example.org/prices
mrf-url: https://example.org/south_standardcharges.csv
"""


def response(status: int, content_type: str = "text/plain", **headers: str) -> httpx.Response:
    return httpx.Response(status, headers={"content-type": content_type, **headers})


def test_fetch_status_ok_for_plain_text():
    assert fetch_status(response(200)) == "ok"


def test_fetch_status_detects_cloudflare_challenge():
    assert fetch_status(response(403, "text/html", **{"cf-mitigated": "challenge"})) == (
        "blocked_bot_challenge"
    )


def test_fetch_status_flags_html_served_as_200():
    # Some sites answer every path with their home page instead of a 404.
    assert fetch_status(response(200, "text/html")) == "not_plain_text"


def test_fetch_status_reports_http_errors():
    assert fetch_status(response(404, "text/html")) == "http_404"


def test_match_location_by_name_ignores_case():
    entries = [{"location-name": "Oro Valley Hospital"}, {"location-name": "Other"}]
    assert match_location(entries, "ORO VALLEY HOSPITAL") == entries[0]


def test_match_location_uses_single_entry_when_no_name_curated():
    entries = [{"location-name": "Only One"}]
    assert match_location(entries, None) == entries[0]
    assert match_location(entries + [{"location-name": "Two"}], None) is None


def test_source_row_picks_the_hospital_from_a_system_file():
    row = source_row(
        "030111",
        "https://example.org/",
        "Banner University Medical Center South",
        "ok",
        SYSTEM_FILE,
    )
    assert row["status"] == "found"
    assert row["cms_hpt_url"] == "https://example.org/cms-hpt.txt"
    assert row["mrf_url"] == "https://example.org/south_standardcharges.csv"


def test_source_row_reports_missing_location():
    row = source_row("1", "https://example.org", "Not Listed", "ok", SYSTEM_FILE)
    assert row["status"] == "no_matching_location"
    assert row["mrf_url"] == ""


def test_source_row_marks_files_only_served_to_browsers():
    row = source_row(
        "030064", "https://example.org", "Banner University Medical Center Tucson",
        "browser_ua_only", SYSTEM_FILE,
    )  # fmt: skip
    assert row["status"] == "found_browser_ua_only"
    assert row["mrf_url"] == "https://example.org/tucson_standardcharges.csv"


def test_source_row_uses_a_manual_copy_and_records_it():
    row = source_row(
        "030010", "https://example.org", "Banner University Medical Center Tucson",
        "manual_copy", SYSTEM_FILE,
    )  # fmt: skip
    assert row["status"] == "found_manual_copy"
    assert row["mrf_url"] == "https://example.org/tucson_standardcharges.csv"


def test_manual_copies_have_no_contact_details():
    # The repo is public; people's names and emails stay out of it.
    for path in MANUAL_DIR.glob("*.txt"):
        assert "contact-" not in path.read_text(encoding="utf-8"), path.name


def test_source_row_keeps_fetch_failures():
    row = source_row("1", "https://example.org", None, "blocked_bot_challenge", "")
    assert row["status"] == "blocked_bot_challenge"
