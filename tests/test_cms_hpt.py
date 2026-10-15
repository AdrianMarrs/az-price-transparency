from ingest.hospitals.cms_hpt import parse_cms_hpt

SAMPLE = """\
location-name: Example Hospital
source-page-url: https://example.org/price-transparency
mrf-url: https://example.org/files/123456789_example-hospital_standardcharges.csv
contact-name: Jane Doe
contact-email: pricing@example.org

location-name: Example Hospital North
source-page-url: https://example.org/price-transparency
mrf-url: https://example.org/files/987654321_example-north_standardcharges.json
contact-name: Jane Doe
contact-email: pricing@example.org
"""


def test_parses_each_location_block():
    entries = parse_cms_hpt(SAMPLE)
    assert len(entries) == 2
    assert entries[0]["location-name"] == "Example Hospital"
    assert entries[1]["mrf-url"].endswith("_standardcharges.json")


def test_keeps_colons_in_urls():
    entries = parse_cms_hpt("mrf-url: https://example.org/a.csv")
    assert entries == [{"mrf-url": "https://example.org/a.csv"}]


def test_handles_windows_line_endings_and_extra_blank_lines():
    text = "\r\n\r\nlocation-name: A\r\nmrf-url: https://a.org/x.csv\r\n\r\n\r\n"
    assert parse_cms_hpt(text) == [{"location-name": "A", "mrf-url": "https://a.org/x.csv"}]


def test_lowercases_keys_and_ignores_junk_lines():
    text = "Location-Name: A\nnot a key value line\nMRF-URL: https://a.org/x.csv"
    assert parse_cms_hpt(text) == [{"location-name": "A", "mrf-url": "https://a.org/x.csv"}]


def test_empty_file_returns_no_entries():
    assert parse_cms_hpt("") == []
