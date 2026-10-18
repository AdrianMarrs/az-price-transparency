"""Build the hospital list seed from CMS's Hospital General Information file.

Usage:
    uv run python -m ingest.hospitals.hospital_list [--state AZ] [--county PIMA]

Writes warehouse/seeds/hospitals.csv: every state, or one with --state. Federally run hospitals (VA, Indian Health
Service, tribal, military) are kept but flagged, because the price transparency
rule does not apply to them the same way.
"""

import argparse
from pathlib import Path

import httpx
import polars as pl

DATASET_ID = "xubh-q36u"
METASTORE_URL = (
    "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/"
    f"{DATASET_ID}?show-reference-ids=false"
)
RAW_PATH = Path("data/reference/hospital_general_information.csv")
SEED_PATH = Path("warehouse/seeds/hospitals.csv")

FEDERAL_OWNERSHIP = {
    "Government - Federal",
    "Veterans Health Administration",
    "Tribal",
}

COLUMNS = {
    "Facility ID": "ccn",
    "Facility Name": "name",
    "Address": "address",
    "City/Town": "city",
    "State": "state",
    "ZIP Code": "zip",
    "County/Parish": "county",
    "Telephone Number": "phone",
    "Hospital Type": "hospital_type",
    "Hospital Ownership": "ownership",
}


def current_download_url(client: httpx.Client) -> tuple[str, str]:
    """Return (download URL, last modified date) for the dataset.

    The file URL changes with each CMS refresh, so look it up rather than hard-coding it.
    """
    meta = client.get(METASTORE_URL).raise_for_status().json()
    dist = meta["distribution"][0]
    dist = dist.get("data", dist)  # entries are sometimes wrapped in {"identifier", "data"}
    return dist["downloadURL"], meta["modified"]


def download(client: httpx.Client, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with dest.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)


def build_hospital_list(raw: pl.DataFrame, state: str | None, county: str | None) -> pl.DataFrame:
    df = raw.select(list(COLUMNS)).rename(COLUMNS)
    if state:
        df = df.filter(pl.col("state") == state.upper())
    if county:
        df = df.filter(pl.col("county").str.to_uppercase() == county.upper())
    return df.with_columns(
        pl.col("ownership").is_in(FEDERAL_OWNERSHIP).alias("federally_run")
    ).sort("state", "city", "name")


def refresh_hospital_list(
    state: str | None = None, county: str | None = None
) -> tuple[pl.DataFrame, str]:
    """Download the current CMS file and rewrite the hospitals seed; returns (seed, modified)."""
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        url, modified = current_download_url(client)
        download(client, url, RAW_PATH)

    raw = pl.read_csv(RAW_PATH, infer_schema_length=0)
    hospitals = build_hospital_list(raw, state, county)
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    hospitals.write_csv(SEED_PATH)
    return hospitals, modified


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", help="one state (default: every state)")
    parser.add_argument("--county", help="optional, e.g. PIMA")
    args = parser.parse_args()

    hospitals, modified = refresh_hospital_list(args.state, args.county)
    federal = hospitals.filter(pl.col("federally_run")).height
    print(f"CMS file modified {modified}; {hospitals.height} hospitals written to {SEED_PATH}")
    print(f"{federal} federally run (flagged), {hospitals.height - federal} in scope")


if __name__ == "__main__":
    main()
