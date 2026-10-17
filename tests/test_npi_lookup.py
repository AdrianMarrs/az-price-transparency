from ingest.hospitals.npi_lookup import address_key, name_query, name_rows, npi_rows


def test_address_key_normalizes_street_words_and_suites():
    assert address_key("5301 East Grant Road, Suite 100") == "5301 GRANT"
    assert address_key("5301 E GRANT RD") == "5301 GRANT"


def test_address_key_ignores_directions_and_street_types():
    # registrations that missed before (October 2026): Little Colorado, Wickenburg, Kingman
    assert address_key("1501 NORTH WILLIAMSON AVENUE") == address_key("1501 WILLIAMSON AVE")
    assert address_key("520 ROSE LANE") == address_key("520 ROSE LN")
    assert address_key("3269 STOCKTON HILL ROAD") == address_key("3269 N STOCKTON HILL RD")
    assert address_key("2400 SOUTH AVENUE A") == address_key("2400 S AVE A")  # Yuma Regional
    assert address_key("5301 E GRANT RD") != address_key("5302 E GRANT RD")


def test_address_key_ignores_punctuation():
    assert address_key("1601 W. St. Mary's Rd.") == address_key("1601 W ST MARYS RD")


def record(npi, address, taxonomy="282N00000X", primary=True, subpart="NO", city="TUCSON"):
    return {
        "number": npi,
        "basic": {"organization_name": "X", "organizational_subpart": subpart, "status": "A"},
        "addresses": [
            {"address_purpose": "MAILING", "address_1": "PO BOX 1", "city": "ELSEWHERE"},
            {"address_purpose": "LOCATION", "address_1": address, "city": city},
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


def test_npi_rows_record_how_they_matched():
    rows = npi_rows("030006", "5301 E GRANT RD", [record(1, "5301 E Grant Rd")])
    assert rows[0]["match"] == "address"


def test_name_query_uses_the_first_two_words():
    assert name_query("BANNER BOSWELL MEDICAL CENTER") == "BANNER BOSWELL*"
    assert name_query("PHOENIX MEDICAL PSYCHIATRIC HOSPITAL, LLC") == "PHOENIX MEDICAL*"


def test_name_rows_keep_hospitals_in_the_same_city_only():
    records = [
        record(1, "10401 W THUNDERBIRD BLVD", city="SUN CITY"),
        record(2, "12023 W WINDROSE DR", city="EL MIRAGE"),  # same name, another town
        record(3, "10401 W THUNDERBIRD BLVD", taxonomy="207L00000X", city="SUN CITY"),
    ]
    rows = name_rows("030061", "Sun City", records)
    assert [(r["npi"], r["match"]) for r in rows] == [(1, "name")]
