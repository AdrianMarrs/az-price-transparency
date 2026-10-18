"""Check each hospital against the price transparency rules we can test from outside.

Usage:
    uv run python -m ingest.hospitals.compliance

Reads the discovery results (warehouse/seeds/hospital_sources.csv), the latest download
attempt per hospital (raw.source_files), the parse report (data/parsed/parse_report.csv) and
the loaded prices (raw.hospital_charges), all in the Parquet lake but the seed and report,
and writes one row per hospital x rule to raw.compliance_checks
(raw/compliance_checks/checks.parquet, rewritten each run). passed is null when a
rule can't be checked, e.g. content rules when no file could be obtained.

These are our readings of 45 CFR 180.50 and the CMS template, not CMS's own validator.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from ingest import lake
from ingest.hospitals import source_log

SOURCES_PATH = Path("warehouse/seeds/hospital_sources.csv")
HOSPITALS_PATH = Path("warehouse/seeds/hospitals.csv")
REPORT_PATH = Path("data/parsed/parse_report.csv")

RULES = {
    "cms_hpt_lists_hospital": "cms-hpt.txt at the website root names this hospital's price file",
    "cms_hpt_machine_readable": "cms-hpt.txt is well-formed and readable by a program",
    "price_file_downloads": "the price file it points to can be downloaded",
    "price_file_parses": "the price file can be read as a CMS template file",
    "version_stated": "the file states its template version",
    "header_fields_present": "the file's header has every required field filled in",
    "payer_prices_present": "the file includes payer-specific negotiated charges",
    "mostly_dollar_prices": "at least half of its unbundled insurer prices are dollar amounts",
    "updated_within_12_months": "the file was updated in the last 12 months",
    "shoppable_cash_prices": "at least 90% of the shoppable services it prices have a cash price",
    "shoppable_list_prices": "at least 90% of the shoppable services it prices have a list price",
}
CONTENT_RULES = list(RULES)[3:]
READABLE = {"parsed", "partly_parsed", "no_service_codes"}
# The rule asks for a cash and a gross (list) price for every item and service "as
# applicable". Many files give a procedure only insurer prices (it's charged as separate
# items), so a few gaps are allowed; most of the shoppable services they price aren't.
STANDARD_CHARGE_SHARE = 0.9

# CMS template v2/v3 header fields. CSV names the attestation by its full text.
REQUIRED_HEADER = {
    "hospital_name": ("hospital_name",),
    "last_updated_on": ("last_updated_on",),
    "version": ("version",),
    "location_name": ("location_name",),
    "hospital_address": ("hospital_address",),
    "license_number": ("license_number", "license_information"),
    "type_2_npi": ("type_2_npi",),
    "attestation": ("to the best of its knowledge", "attestation"),
}


def missing_header_fields(header_fields: str | None) -> list[str]:
    present = [f.lower() for f in (header_fields or "").split(";") if f]
    return [name for name, prefixes in REQUIRED_HEADER.items()
            if not any(f.startswith(p) for f in present for p in prefixes)]  # fmt: skip


def check_hospital(source: dict, download: dict | None, parse: dict | None, today: date) -> list:
    """(rule, passed, detail) for one hospital. passed is None when it can't be checked."""
    status = source.get("status") or "website_not_found"
    checks = [
        ("cms_hpt_lists_hospital", status.startswith("found"), status),
        ("cms_hpt_machine_readable", status == "found", status),
    ]
    if not source.get("mrf_url"):
        checks.append(("price_file_downloads", False, "no price file URL found"))
    elif download is None:
        checks.append(("price_file_downloads", None, "not attempted"))
    else:
        ok = download["outcome"] in ("downloaded", "unchanged", "skipped_too_large")
        if download.get("access") == "manual_download":  # programs are refused it
            ok, download = False, {"outcome": "blocked for programs; downloaded by hand"}
        elif download.get("access") == "browser_download":
            ok, download = False, {"outcome": "blocked for programs; downloaded with a browser"}
        checks.append(("price_file_downloads", ok, download.get("error") or download["outcome"]))

    if parse is None or parse.get("outcome") == "deferred_too_large":
        detail = parse["error"] if parse else "no file to check"
        return checks + [(rule, None, detail) for rule in CONTENT_RULES]
    if parse["outcome"] not in READABLE:
        return (
            checks
            + [("price_file_parses", False, parse.get("error") or parse["outcome"])]
            + [(rule, None, "file could not be read") for rule in CONTENT_RULES[1:]]
        )

    missing = missing_header_fields(parse.get("header_fields"))
    prices = int(parse.get("file_payer_prices") or 0)
    dollar = int(parse.get("file_payer_dollar") or 0)
    unbundled = prices - int(parse.get("file_payer_bundled") or 0)
    updated = date.fromisoformat(parse["last_updated_on"]) if parse.get("last_updated_on") else None
    shoppable = int(parse.get("shoppable_services") or 0)
    checks += [
        ("price_file_parses", True, parse["outcome"]),
        ("version_stated", bool(parse.get("version")), parse.get("version") or "missing"),
        ("header_fields_present", not missing,
         "missing: " + ", ".join(missing) if missing else "all present"),
        ("payer_prices_present", prices > 0, f"{prices:,} insurer prices"),
        ("mostly_dollar_prices",
         None if unbundled <= 0 else dollar / unbundled >= 0.5,
         f"{dollar / unbundled:.0%} in dollars" if unbundled > 0 else "no unbundled insurer prices"),
        ("updated_within_12_months",
         updated is not None and updated >= today - timedelta(days=365),
         str(updated) if updated else "no valid last_updated_on date"),
        standard_charge_check("shoppable_cash_prices", shoppable,
                              int(parse.get("shoppable_with_cash") or 0), "cash price"),
        standard_charge_check("shoppable_list_prices", shoppable,
                              int(parse.get("shoppable_with_gross") or 0), "list price"),
    ]  # fmt: skip
    return checks


def standard_charge_check(rule: str, services: int, priced: int, what: str) -> tuple:
    """(rule, passed, detail) for the share of shoppable services with a cash or list price;
    None when the file prices no shoppable services."""
    if services == 0:
        return rule, None, "no shoppable services priced"
    return (rule, priced / services >= STANDARD_CHARGE_SHARE,
            f"{priced} of {services} shoppable services have a {what}")  # fmt: skip


def shoppable_standard_charges() -> dict[str, dict]:
    """Per hospital: how many CMS shoppable services its file prices, and how many of those
    have a cash price and a list (gross) price."""
    df = lake.read(
        "raw/hospital_charges/*/*/*.parquet",
        sql="""
        SELECT ccn, count(*) AS n, count(*) FILTER (WHERE cash) AS cash,
               count(*) FILTER (WHERE gross) AS gross
        FROM (SELECT ccn, code_type, code,
                     bool_or(price_type = 'discounted_cash' AND amount IS NOT NULL) AS cash,
                     bool_or(price_type = 'gross' AND amount IS NOT NULL) AS gross
              FROM {} WHERE cms_shoppable_id IS NOT NULL
              GROUP BY ccn, code_type, code) AS s
        GROUP BY ccn""",
    )
    return {r["ccn"]: {"shoppable_services": r["n"], "shoppable_with_cash": r["cash"],
                       "shoppable_with_gross": r["gross"]} for r in df.to_dicts()}  # fmt: skip


def parse_reports() -> dict[str, dict]:
    """Each hospital's latest parse: data/parsed/parse_report.csv (a local run), overridden
    by raw/parse_reports in the lake (the cloud pipeline's runs, ingest/pipeline.py)."""
    report = {}
    if REPORT_PATH.exists():
        report = {r["ccn"]: r for r in pl.read_csv(REPORT_PATH, infer_schema_length=0).to_dicts()}
    runs = lake.read("raw/parse_reports/*.parquet")
    if not runs.is_empty():
        latest = runs.sort("parsed_at").group_by("ccn").last().drop("parsed_at")
        report |= {r["ccn"]: {k: v for k, v in r.items() if v is not None}
                   for r in latest.to_dicts()}  # fmt: skip
    return report


def main() -> pl.DataFrame:
    hospitals = pl.read_csv(HOSPITALS_PATH, infer_schema_length=0).filter(
        pl.col("federally_run") == "false"
    )
    sources = {r["ccn"]: r for r in pl.read_csv(SOURCES_PATH, infer_schema_length=0).to_dicts()}
    report = parse_reports()
    checked_at = datetime.now(UTC)

    downloads = source_log.latest(source_log.read())
    for ccn, counts in shoppable_standard_charges().items():
        if ccn in report:
            report[ccn] = report[ccn] | counts
    rows = [
        (ccn, rule, passed, detail, checked_at)
        for ccn in hospitals["ccn"]
        for rule, passed, detail in check_hospital(
            sources.get(ccn, {}), downloads.get(ccn), report.get(ccn), checked_at.date()
        )
    ]
    df = pl.DataFrame(rows, orient="row", schema={
        "ccn": pl.String, "rule": pl.String, "passed": pl.Boolean, "detail": pl.String,
        "checked_at": pl.Datetime("us", "UTC")})  # fmt: skip
    lake.replace_folder("raw/compliance_checks", df, "checks.parquet")
    summary = df.group_by("rule").agg(
        pl.col("passed").sum().alias("pass"),
        (~pl.col("passed")).sum().alias("fail"),
        pl.col("passed").is_null().sum().alias("not_checked"),
    )
    order = {rule: i for i, rule in enumerate(RULES)}
    print(summary.sort(pl.col("rule").replace_strict(order)))
    return df


if __name__ == "__main__":
    main()
