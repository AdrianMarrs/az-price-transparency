"""Write the hospital seeds for every state from national discovery.

Usage:
    uv run python -m ingest.national.seeds

warehouse/seeds/hospitals.csv: every hospital in CMS's Hospital General Information file,
federally run ones flagged as before (data/reference/hospital_general_information.csv,
downloaded by ingest.hospitals.hospital_list or ingest.national.discover).

warehouse/seeds/hospital_sources.csv: for hospitals curated by hand (hospital_websites.csv,
Arizona's), the rows ingest.hospitals.find_sources wrote, kept as they are; for every other
in-scope hospital, the automatic match from data/national/sources.parquet
(ingest.national.discover), in the same columns and vocabulary. A system_match keeps that
status: the file was found on a health system's site, not confirmed at the hospital's own
website root, so the cms-hpt.txt rule isn't counted as passed.
"""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from ingest.hospitals.find_sources import OUTPUT_PATH as SOURCES_PATH
from ingest.hospitals.find_sources import WEBSITES_PATH
from ingest.hospitals.hospital_list import RAW_PATH, SEED_PATH, build_hospital_list

NATIONAL_PATH = Path("data/national/sources.parquet")
SOURCE_COLUMNS = ["ccn", "cms_hpt_url", "status", "location_name", "source_page_url",
                  "mrf_url", "website_source", "checked_at"]  # fmt: skip


def national_sources(national: pl.DataFrame, checked_at: str) -> pl.DataFrame:
    """discover's rows in the sources seed's columns."""
    if "checked_at" not in national.columns:
        national = national.with_columns(pl.lit(checked_at).alias("checked_at"))
    return national.select(
        "ccn",
        pl.when(pl.col("website") != "")
        .then(pl.col("website") + "/cms-hpt.txt")
        .otherwise(pl.lit(""))
        .alias("cms_hpt_url"),
        pl.col("status").replace({"no_website": "website_not_found"}),
        "location_name",
        "source_page_url",
        "mrf_url",
        pl.col("website_source").fill_null(""),
        "checked_at",
    )


def merge_sources(curated: pl.DataFrame, national: pl.DataFrame) -> pl.DataFrame:
    """The curated rows, plus national rows for every hospital not curated."""
    rest = national.filter(~pl.col("ccn").is_in(curated["ccn"].to_list()))
    return pl.concat([curated.select(SOURCE_COLUMNS), rest.select(SOURCE_COLUMNS)]).sort("ccn")


def main() -> None:
    raw = pl.read_csv(RAW_PATH, infer_schema_length=0)
    hospitals = build_hospital_list(raw, None, None)
    hospitals.write_csv(SEED_PATH)

    curated_ccns = pl.read_csv(WEBSITES_PATH, infer_schema_length=0)["ccn"].to_list()
    curated = pl.read_csv(SOURCES_PATH, infer_schema_length=0).filter(
        pl.col("ccn").is_in(curated_ccns)
    )
    modified = datetime.fromtimestamp(NATIONAL_PATH.stat().st_mtime, UTC)
    national = national_sources(pl.read_parquet(NATIONAL_PATH),
                                modified.strftime("%Y-%m-%dT%H:%M:%SZ"))  # fmt: skip
    sources = merge_sources(curated, national)
    sources.write_csv(SOURCES_PATH)

    in_scope = hospitals.filter(~pl.col("federally_run"))
    print(f"{hospitals.height:,} hospitals ({in_scope.height:,} in scope) -> {SEED_PATH}")
    print(f"{sources.height:,} sources ({curated.height} curated) -> {SOURCES_PATH}")
    print(sources["status"].value_counts(sort=True).head(8))


if __name__ == "__main__":
    main()
