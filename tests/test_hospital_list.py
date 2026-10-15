import polars as pl

from ingest.hospitals.hospital_list import COLUMNS, build_hospital_list


def make_raw(rows: list[dict[str, str]]) -> pl.DataFrame:
    return pl.DataFrame([{col: row.get(col, "") for col in COLUMNS} for row in rows])


RAW = make_raw(
    [
        {
            "Facility ID": "1",
            "Facility Name": "A",
            "State": "AZ",
            "County/Parish": "PIMA",
            "City/Town": "TUCSON",
            "Hospital Ownership": "Proprietary",
        },
        {
            "Facility ID": "2",
            "Facility Name": "VA",
            "State": "AZ",
            "County/Parish": "Pima",
            "City/Town": "TUCSON",
            "Hospital Ownership": "Veterans Health Administration",
        },
        {
            "Facility ID": "3",
            "Facility Name": "B",
            "State": "AZ",
            "County/Parish": "MARICOPA",
            "City/Town": "PHOENIX",
            "Hospital Ownership": "Proprietary",
        },
        {
            "Facility ID": "4",
            "Facility Name": "C",
            "State": "NM",
            "County/Parish": "PIMA",
            "City/Town": "X",
            "Hospital Ownership": "Proprietary",
        },
    ]
)


def test_filters_by_state():
    assert build_hospital_list(RAW, "az", None)["ccn"].to_list() == ["3", "1", "2"]


def test_filters_by_county_case_insensitively():
    assert set(build_hospital_list(RAW, "AZ", "pima")["ccn"]) == {"1", "2"}


def test_flags_federally_run_hospitals():
    result = build_hospital_list(RAW, "AZ", "PIMA")
    flagged = dict(zip(result["ccn"], result["federally_run"]))
    assert flagged == {"1": False, "2": True}


def test_renames_columns():
    assert set(COLUMNS.values()) <= set(build_hospital_list(RAW, "AZ", None).columns)
