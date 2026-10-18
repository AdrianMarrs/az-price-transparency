from datetime import date

from ingest.hospitals.compliance import RULES, check_hospital, missing_header_fields

TODAY = date(2026, 10, 16)
CSV_HEADER = ("hospital_name;last_updated_on;version;location_name;hospital_address;"
              "license_number|AZ;type_2_npi;to the best of its knowledge and belief, th;"
              "attester_name")  # fmt: skip
GOOD_PARSE = {
    "outcome": "parsed", "version": "3.0.0", "last_updated_on": "2026-04-30",
    "header_fields": CSV_HEADER, "file_payer_prices": "100", "file_payer_dollar": "80",
    "file_payer_bundled": "0", "shoppable_services": 50, "shoppable_with_cash": 50,
    "shoppable_with_gross": 46,
}  # fmt: skip
FOUND = {"status": "found", "mrf_url": "https://x.org/prices.csv"}
DOWNLOADED = {"outcome": "downloaded", "error": None}


def verdicts(*args):
    return {rule: passed for rule, passed, _ in check_hospital(*args, TODAY)}


def test_a_compliant_hospital_passes_every_rule():
    assert verdicts(FOUND, DOWNLOADED, GOOD_PARSE) == {rule: True for rule in RULES}


def test_header_check_reads_csv_and_json_names():
    assert missing_header_fields(CSV_HEADER) == []
    json_keys = ("attestation;hospital_address;hospital_name;last_updated_on;"
                 "license_information;location_name;type_2_npi;version")  # fmt: skip
    assert missing_header_fields(json_keys) == []
    assert missing_header_fields("hospital_name;version") == [
        "last_updated_on", "location_name", "hospital_address", "license_number",
        "type_2_npi", "attestation",
    ]  # fmt: skip


def test_no_insurer_prices_fails_and_skips_the_dollar_rule():
    # St. Joseph's and St. Mary's: list and cash prices only.
    v = verdicts(FOUND, DOWNLOADED, GOOD_PARSE | {"file_payer_prices": "0",
                                                  "file_payer_dollar": "0"})  # fmt: skip
    assert v["payer_prices_present"] is False
    assert v["mostly_dollar_prices"] is None


def test_bundled_prices_dont_count_against_dollar_share():
    # TMC: 17% in dollars overall, but most of the rest is "bundled into the DRG payment".
    parse = GOOD_PARSE | {"file_payer_prices": "100", "file_payer_dollar": "17",
                          "file_payer_bundled": "83"}  # fmt: skip
    assert verdicts(FOUND, DOWNLOADED, parse)["mostly_dollar_prices"] is True


def test_stale_and_undated_files_fail_the_12_month_rule():
    assert verdicts(FOUND, DOWNLOADED, GOOD_PARSE | {"last_updated_on": "2025-09-30"})[
        "updated_within_12_months"] is False  # fmt: skip
    assert verdicts(FOUND, DOWNLOADED, GOOD_PARSE | {"last_updated_on": ""})[
        "updated_within_12_months"] is False  # fmt: skip


def test_blocked_hospital_fails_discovery_and_content_is_not_checked():
    v = verdicts({"status": "blocked_bot_challenge", "mrf_url": ""}, None, None)
    assert v["cms_hpt_lists_hospital"] is False
    assert v["price_file_downloads"] is False
    assert all(v[rule] is None for rule in list(RULES)[3:])


def test_browser_only_access_counts_as_found_but_not_machine_readable():
    v = verdicts({"status": "found_browser_ua_only", "mrf_url": "u"}, DOWNLOADED, GOOD_PARSE)
    assert v["cms_hpt_lists_hospital"] is True
    assert v["cms_hpt_machine_readable"] is False


def test_too_large_to_parse_yet_is_not_held_against_the_hospital():
    v = verdicts(FOUND, {"outcome": "skipped_too_large", "error": "21.5 GB"},
                 {"outcome": "deferred_too_large", "error": "21.5 GB"})  # fmt: skip
    assert v["price_file_downloads"] is True
    assert all(v[rule] is None for rule in list(RULES)[3:])


def test_unreadable_file_fails_parse_rule_only():
    v = verdicts(FOUND, DOWNLOADED, {"outcome": "failed", "error": "JSONDecodeError"})
    assert v["price_file_parses"] is False
    assert all(v[rule] is None for rule in list(RULES)[4:])


def test_a_hand_download_fails_the_download_rule_but_its_contents_are_checked():
    manual = DOWNLOADED | {"access": "manual_download"}
    v = verdicts(FOUND, manual, GOOD_PARSE)
    assert v["price_file_downloads"] is False
    assert v["payer_prices_present"] is True


def test_cash_and_list_prices_are_needed_for_most_shoppable_services():
    # HonorHealth John C. Lincoln: insurer prices only for 33 of its 74 shoppable services.
    v = verdicts(FOUND, DOWNLOADED, GOOD_PARSE | {"shoppable_services": 74,
                                                  "shoppable_with_cash": 41,
                                                  "shoppable_with_gross": 41})  # fmt: skip
    assert v["shoppable_cash_prices"] is False
    assert v["shoppable_list_prices"] is False
    assert v["payer_prices_present"] is True


def test_no_shoppable_services_leaves_the_standard_charge_rules_unchecked():
    v = verdicts(FOUND, DOWNLOADED, GOOD_PARSE | {"shoppable_services": 0})
    assert v["shoppable_cash_prices"] is None
    assert v["shoppable_list_prices"] is None
