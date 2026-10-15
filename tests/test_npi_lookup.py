from ingest.hospitals.npi_lookup import address_key, npi_rows


def test_address_key_normalizes_street_words_and_suites():
    assert address_key("5301 East Grant Road, Suite 100") == "5301 E GRANT"
    assert address_key("5301 E GRANT RD") == "5301 E GRANT"


def test_address_key_ignores_punctuation():
    assert address_key("1601 W. St. Mary's Rd.") == address_key("1601 W ST MARYS RD")


def record(npi, address, taxonomy="282N00000X", primary=True, subpart="NO"):
    return {
        "number": npi,
        "basic": {"organization_name": "X", "organizational_subpart": subpart, "status": "A"},
        "addresses": [
            {"address_purpose": "MAILING", "address_1": "PO BOX 1"},
            {"address_purpose": "LOCATION", "address_1": address},
        ],
        "taxonomies": [{"code": taxonomy, "desc": "d", "primary": primary}],
    }


def test_npi_rows_keeps_only_matching_location_addresses():
    records = [record(1, "5301 E Grant Rd"), record(2, "100 Other St")]
    rows = npi_rows("030006", "5301 EAST GRANT ROAD", records)
    assert [r["npi"] for r in rows] == [1]
    assert rows[0]["ccn"] == "030006"
    assert rows[0]["taxonomy_code"] == "282N00000X"
    assert rows[0]["is_subpart"] is False
    assert rows[0]["role"] == "hospital"


def test_npi_rows_marks_non_hospital_taxonomies_as_co_located():
    records = [record(1, "5301 E Grant Rd", taxonomy="207L00000X")]  # anesthesiology group
    assert npi_rows("030006", "5301 E GRANT RD", records)[0]["role"] == "co_located"
