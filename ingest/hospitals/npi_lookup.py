"""Find every organization NPI registered at each hospital's address.

Usage:
    uv run python -m ingest.hospitals.npi_lookup

Reads warehouse/seeds/hospitals.csv and writes warehouse/seeds/hospital_npis.csv,
one row per (hospital, NPI). Hospitals register many NPIs (the hospital itself,
pharmacies, labs, psychiatric units), and insurer files may use any of them, so all
are kept. Matching is by street number and street name within the hospital's ZIP
code, because hospital names repeat across cities.
"""

import re
import time
from pathlib import Path

import httpx
import polars as pl

NPPES_URL = "https://npiregistry.cms.hhs.gov/api/"
PAGE_SIZE = 200
MAX_SKIP = 1000  # NPPES API limit
HOSPITALS_PATH = Path("warehouse/seeds/hospitals.csv")
OUTPUT_PATH = Path("warehouse/seeds/hospital_npis.csv")

# NUCC taxonomy groups: 27x = hospital units (psychiatric, rehab), 28x = hospitals.
# Everything else at the address (physician groups, pharmacies, labs) is "co_located".
HOSPITAL_TAXONOMY_PREFIXES = ("27", "28")

STREET_WORDS = {
    "ROAD": "RD", "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR",
    "EAST": "E", "WEST": "W", "NORTH": "N", "SOUTH": "S", "HIGHWAY": "HWY",
}  # fmt: skip


def address_key(address: str) -> str:
    """Normalize an address to '<number> <first street words>' for matching.

    '5301 East Grant Road, Suite 100' and '5301 E GRANT RD' both become '5301 E GRANT'.
    """
    words = re.sub(r"[^A-Z0-9 ]", " ", address.upper()).split()
    words = [STREET_WORDS.get(w, w) for w in words]
    return " ".join(words[:3])


def fetch_zip(client: httpx.Client, postal_code: str, state: str) -> list[dict]:
    """All organization NPIs with a location in the ZIP code (paged)."""
    results: list[dict] = []
    for skip in range(0, MAX_SKIP + 1, PAGE_SIZE):
        params = {
            "version": "2.1",
            "enumeration_type": "NPI-2",
            "postal_code": postal_code,
            "state": state,
            "address_purpose": "LOCATION",
            "limit": PAGE_SIZE,
            "skip": skip,
        }
        page = client.get(NPPES_URL, params=params).raise_for_status().json()
        batch = page.get("results", [])
        results.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        time.sleep(0.2)
    return results


def npi_rows(ccn: str, hospital_address: str, records: list[dict]) -> list[dict]:
    target = address_key(hospital_address)
    rows = []
    for r in records:
        location = next(a for a in r["addresses"] if a["address_purpose"] == "LOCATION")
        if address_key(location["address_1"]) != target:
            continue
        primary = next((t for t in r["taxonomies"] if t.get("primary")), {})
        code = primary.get("code", "")
        rows.append(
            {
                "ccn": ccn,
                "npi": r["number"],
                "organization_name": r["basic"].get("organization_name", ""),
                "is_subpart": r["basic"].get("organizational_subpart", "") == "YES",
                "taxonomy_code": code,
                "taxonomy_desc": primary.get("desc", ""),
                "role": "hospital" if code.startswith(HOSPITAL_TAXONOMY_PREFIXES) else "co_located",
                "status": r["basic"].get("status", ""),
            }
        )
    return rows


def main() -> None:
    hospitals = pl.read_csv(HOSPITALS_PATH, infer_schema_length=0).filter(
        pl.col("federally_run") == "false"
    )
    rows: list[dict] = []
    cache: dict[str, list[dict]] = {}
    with httpx.Client(timeout=60) as client:
        for h in hospitals.iter_rows(named=True):
            zip5 = h["zip"][:5]
            if zip5 not in cache:
                cache[zip5] = fetch_zip(client, zip5, h["state"])
            found = npi_rows(h["ccn"], h["address"], cache[zip5])
            rows.extend(found)
            print(f"{h['name'][:45]:45} {len(found):3} NPIs")

    out = pl.DataFrame(rows).sort("ccn", "taxonomy_code", "npi")
    out.write_csv(OUTPUT_PATH)
    missing = set(hospitals["ccn"]) - set(out["ccn"])
    print(f"{out.height} NPIs for {out['ccn'].n_unique()} hospitals -> {OUTPUT_PATH}")
    if missing:
        print(f"No NPI match for CCNs: {sorted(missing)} (check their addresses by hand)")


if __name__ == "__main__":
    main()
