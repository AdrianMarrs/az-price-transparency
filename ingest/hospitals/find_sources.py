"""Find each hospital's machine-readable price file through its cms-hpt.txt.

Usage:
    uv run python -m ingest.hospitals.find_sources

Reads warehouse/seeds/hospital_websites.csv (hand-curated: each hospital's website and
the location name its cms-hpt.txt uses) and writes warehouse/seeds/hospital_sources.csv,
one row per hospital with the file's URLs and a status. A status other than "found" is
a compliance finding: CMS requires the file at the website root, readable by machines.

Contact names and emails in cms-hpt.txt are left out on purpose; the repo is public.
"""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl

from ingest.hospitals.cms_hpt import parse_cms_hpt

WEBSITES_PATH = Path("warehouse/seeds/hospital_websites.csv")
OUTPUT_PATH = Path("warehouse/seeds/hospital_sources.csv")
USER_AGENT = "az-price-transparency/0.1 (+https://github.com/AdrianMarrs/az-price-transparency)"
# Some sites refuse non-browser clients with a plain 403. We retry once as a browser and
# record that as its own finding. Bot challenges (e.g. Cloudflare's) are never worked around.
BROWSER_USER_AGENT = "Mozilla/5.0"
# When automated access is blocked, a person can open the file in a browser and save it
# here as <host>.txt (contacts removed). It is used, and the block is still recorded.
MANUAL_DIR = Path(__file__).parent / "manual_cms_hpt"
BLOCKED = {"blocked_bot_challenge", "http_403"}


def manual_copy(url: str) -> str | None:
    path = MANUAL_DIR / f"{httpx.URL(url).host}.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


def fetch(client: httpx.Client, url: str) -> tuple[str, str]:
    """(status, text) for a cms-hpt.txt URL."""
    try:
        response = client.get(url)
        status = fetch_status(response)
        if status == "http_403":
            retry = client.get(url, headers={"User-Agent": BROWSER_USER_AGENT})
            if fetch_status(retry) == "ok":
                return "browser_ua_only", retry.text
        if status in BLOCKED and (text := manual_copy(url)) is not None:
            return "manual_copy", text
        return status, response.text
    except httpx.HTTPError as e:
        return f"error_{type(e).__name__}", ""


def fetch_status(response: httpx.Response) -> str:
    """Classify a cms-hpt.txt response."""
    if response.headers.get("cf-mitigated") == "challenge":
        return "blocked_bot_challenge"
    if response.status_code != 200:
        return f"http_{response.status_code}"
    if not response.headers.get("content-type", "").startswith("text/plain"):
        return "not_plain_text"
    return "ok"


def normalize_name(name: str) -> str:
    """Case, spacing and curly apostrophes ('St. Joseph’s') don't count as differences."""
    return " ".join(name.replace("’", "'").lower().split())


def match_location(entries: list[dict[str, str]], location_name: str | None) -> dict | None:
    """The entry for this hospital: by name, or the only entry when no name is curated."""
    if location_name:
        wanted = normalize_name(location_name)
        return next(
            (e for e in entries if normalize_name(e.get("location-name", "")) == wanted), None
        )
    return entries[0] if len(entries) == 1 else None


def looks_like_price_file(text: str) -> bool:
    """True when /cms-hpt.txt serves the price file itself instead of pointing to it."""
    first = next((line for line in text.splitlines() if line.strip()), "")
    return first.lstrip("﻿").startswith(("hospital_name", "{"))


FOUND_STATUS = {
    "ok": "found",
    "browser_ua_only": "found_browser_ua_only",
    "manual_copy": "found_manual_copy",  # automated access blocked
    "malformed": "found_malformed",  # price file findable, but cms-hpt.txt isn't to spec
}


def source_row(ccn: str, website: str, location_name: str | None, status: str, text: str) -> dict:
    cms_hpt_url = f"{website.rstrip('/')}/cms-hpt.txt" if website else ""
    readable = status in FOUND_STATUS
    if readable and looks_like_price_file(text):
        status, entry = "malformed", {"mrf-url": cms_hpt_url}
    else:
        entries = parse_cms_hpt(text) if readable else []
        entry = match_location(entries, location_name)
        mrf_urls = {e["mrf-url"] for e in entries if e.get("mrf-url")}
        named = any(e.get("location-name") for e in entries)
        if readable and entry is None and not named and len(mrf_urls) == 1:
            # Keys missing or split across blank lines, but one price file is named.
            status, entry = "malformed", {"mrf-url": mrf_urls.pop()}
        elif readable and entry is None:
            status = "no_matching_location"
    entry = entry or {}
    return {
        "ccn": ccn,
        "cms_hpt_url": cms_hpt_url,
        "status": FOUND_STATUS.get(status, status),
        "location_name": entry.get("location-name", ""),
        "source_page_url": entry.get("source-page-url", ""),
        "mrf_url": entry.get("mrf-url", ""),
    }


def main() -> None:
    sites = pl.read_csv(WEBSITES_PATH, infer_schema_length=0)
    checked_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched: dict[str, tuple[str, str]] = {}
    rows = []
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
        for s in sites.iter_rows(named=True):
            website = s["website"] or ""
            if not website:
                status, text = "website_not_found", ""
            else:
                url = f"{website.rstrip('/')}/cms-hpt.txt"
                if url not in fetched:
                    fetched[url] = fetch(client, url)
                status, text = fetched[url]
            row = source_row(s["ccn"], website, s["location_name"], status, text)
            rows.append(row | {"website_source": s["website_source"]})

    out = pl.DataFrame(rows).with_columns(pl.lit(checked_at).alias("checked_at")).sort("ccn")
    out.write_csv(OUTPUT_PATH)
    for r in out.iter_rows(named=True):
        print(f"{r['ccn']}  {r['status']:22} {r['location_name'] or '-'}")
    print(out["status"].value_counts(sort=True))
    found = out.filter(pl.col("status").str.starts_with("found")).height
    print(f"{found} of {out.height} hospitals found -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
