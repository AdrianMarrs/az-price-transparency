"""Find price files for every US hospital: a first, automatic pass at national discovery.

Usage:
    uv run python -m ingest.national.discover [--state TX ...] [--refresh]

Arizona's 95 were found partly by hand (docs/02-arizona.md). Nationally that doesn't scale,
so this pass is automatic and measures how far automation gets:

1. Hospitals: CMS's Hospital General Information file, every state, federally run ones
   (VA, IHS, tribal, military) left out as in Arizona.
2. Websites: the homepage DoltHub's community dataset has for each CCN
   (dolthub/hospital-price-transparency-v3). CMS's list has no websites. For a hospital
   DoltHub has none for, Wikidata's official website for a hospital in the same state
   whose name matches near-exactly and unambiguously (and names its city, or shares at
   least three distinctive words), as for system matches below.
3. cms-hpt.txt: fetched once per website (16 at a time, one request per host), with the
   same rules as Arizona (ingest/hospitals/find_sources.fetch: a plain 403 retried once
   as a browser, bot challenges recorded, not worked around).
   Plus the websites of large health systems (ingest/national/systems.txt), whose files
   list many hospitals each.
4. Matching: a hospital takes the entry in its own website's file whose location name
   matches its name best (distinctive words, so "Banner Desert Medical Center" isn't
   "Banner Del E. Webb Medical Center"), or the only entry when the file lists one. A
   hospital with no match there may take an entry from any file fetched, but only a
   near-exact, unambiguous name match that also names its city or shares at least three
   distinctive words ("system_match").

Everything is cached under data/national/ (homepages, every cms-hpt.txt fetched), so a
rerun only fetches what's missing; --refresh starts over. Writes data/national/sources.parquet
and prints coverage by status and state.
"""

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import httpx
import polars as pl

from ingest.hospitals.cms_hpt import parse_cms_hpt
from ingest.hospitals.find_sources import FOUND_STATUS, USER_AGENT, fetch, looks_like_price_file
from ingest.hospitals.hospital_list import (
    COLUMNS,
    FEDERAL_OWNERSHIP,
    RAW_PATH,
    current_download_url,
    download,
)

OUT = Path("data/national")
DOLTHUB = "https://www.dolthub.com/api/v1alpha1/dolthub/hospital-price-transparency-v3/main"
WIKIDATA = "https://query.wikidata.org/sparql"
# US hospitals (and subclasses) with an official website, their state's code and the place
# they're in (often a city).
WIKIDATA_QUERY = """SELECT ?item ?itemLabel ?website ?stateCode ?cityLabel WHERE {
  ?item wdt:P31/wdt:P279* wd:Q16917;
        wdt:P17 wd:Q30;
        wdt:P856 ?website.
  OPTIONAL { ?item wdt:P131 ?city. }
  OPTIONAL { ?item wdt:P131+ ?st. ?st wdt:P31 wd:Q35657; wdt:P300 ?stateCode. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""
THREADS = 16
SYSTEMS_PATH = Path(__file__).with_name("systems.txt")

# Words that say what kind of place it is rather than which one.
GENERIC = {
    "HOSPITAL", "HOSPITALS", "MEDICAL", "CENTER", "CENTRE", "CTR", "MED", "HEALTH",
    "HEALTHCARE", "CARE", "INC", "LLC", "THE", "OF", "AND", "AT", "A", "SYSTEM", "SYSTEMS",
    "CAMPUS", "CLINIC", "SERVICES", "CORPORATION", "CORP", "CO", "DBA", "HOSP",
}  # fmt: skip
SYNONYMS = {"ST": "SAINT", "MT": "MOUNT", "FT": "FORT", "N": "NORTH", "S": "SOUTH",
            "E": "EAST", "W": "WEST", "REG": "REGIONAL", "MEM": "MEMORIAL", "UNIV": "UNIVERSITY"}  # fmt: skip


def words(name: str) -> set[str]:
    """The distinctive words of a hospital or location name, spelled out."""
    tokens = re.findall(r"[A-Z0-9]+", name.upper().replace("’", "'").replace("'S", "S"))
    return {SYNONYMS.get(t, t) for t in tokens} - GENERIC


def name_score(hospital: str, location: str) -> float:
    """How well a cms-hpt.txt location name matches a hospital's name: the share of the
    hospital's distinctive words found in it, less a little for extra words."""
    h, loc = words(hospital), words(location)
    if not h or not loc:
        return 0.0
    shared = len(h & loc)
    return shared / len(h) - 0.1 * len(loc - h) / len(loc)


DIRECTIONS = {"NORTH", "SOUTH", "EAST", "WEST", "CENTRAL", "UPPER", "LOWER"}


def best_entry(name: str, entries: list[dict], host: str = "") -> tuple[dict | None, float]:
    """The entry for this hospital and its score, or (None, best score): the only entry in a
    one-location file; else the one entry whose distinctive words are exactly the
    hospital's; else the best name match (0.75 or better, and clearly ahead of the next).
    Failing that, a full match without the hospital's brand: the part of its name before
    " - " ("KAISER FOUNDATION HOSPITAL - VACAVILLE" is "Vacaville Medical Center" in
    Kaiser's own file), or words in the website's host ("Mercy" on mercy.com)."""
    named = [e for e in entries if e.get("location-name")]
    if len(entries) == 1:
        return entries[0], 1.0
    mine = words(name)
    exact = [e for e in named if words(e["location-name"]) == mine]
    if mine and len({e.get("mrf-url") for e in exact}) == 1:
        return exact[0], 1.0
    entry, score = scored_match(name, named)
    if entry is not None:
        return entry, score
    host_word = host.upper().replace("-", "")
    unbranded = [name.rsplit(" - ", 1)[1]] if " - " in name else []
    unbranded.append(" ".join(sorted(w for w in mine if w not in host_word)))
    for rest in unbranded:
        distinctive = words(rest) - DIRECTIONS
        if words(rest) != mine and any(len(w) >= 4 for w in distinctive):
            entry, branded = scored_match(rest, named, minimum=1.0)
            if entry is not None:
                return entry, branded
    return None, score


def scored_match(name: str, named: list[dict], minimum: float = 0.75
                 ) -> tuple[dict | None, float]:  # fmt: skip
    scored = sorted(((name_score(name, e["location-name"]), i) for i, e in enumerate(named)),
                    reverse=True)  # fmt: skip
    if not scored or scored[0][0] < minimum:
        return None, scored[0][0] if scored else 0.0
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.05:
        return None, scored[0][0]  # two equally good: don't guess
    return named[scored[0][1]], scored[0][0]


def system_roots() -> list[str]:
    lines = SYSTEMS_PATH.read_text(encoding="utf-8").splitlines()
    return [f"https://{d.strip()}" for d in lines if d.strip() and not d.startswith("#")]


class Index:
    """Every entry of every cms-hpt.txt fetched, looked up by distinctive word."""

    def __init__(self, fetched: dict[str, tuple[str, str]]):
        self.entries: list[tuple[str, dict]] = []
        self.by_word: dict[str, set[int]] = {}
        for root, (status, text) in fetched.items():
            if status not in FOUND_STATUS or looks_like_price_file(text):
                continue
            for e in parse_cms_hpt(text):
                if e.get("location-name") and e.get("mrf-url"):
                    i = len(self.entries)
                    self.entries.append((root, e))
                    for w in words(e["location-name"]):
                        self.by_word.setdefault(w, set()).add(i)

    def match(self, name: str, city: str) -> tuple[str, dict, float] | None:
        """A near-exact, unambiguous match for this hospital anywhere, or None."""
        mine = words(name)
        candidates = set().union(*(self.by_word.get(w, set()) for w in mine)) if mine else set()
        scored = sorted(((name_score(name, self.entries[i][1]["location-name"]), i)
                         for i in candidates), reverse=True)  # fmt: skip
        if not scored or scored[0][0] < 0.9:
            return None
        top = [i for sc, i in scored if sc >= scored[0][0] - 0.05]
        if len({self.entries[i][1]["mrf-url"] for i in top}) > 1:
            return None  # the same name in two places (e.g. two "Memorial Hospital"s)
        root, entry = self.entries[top[0]]
        text = " ".join(entry.get(k, "") for k in ("location-name", "source-page-url", "mrf-url"))
        names_city = city and city.lower().replace(" ", "") in text.lower().replace(
            " ", ""
        ).replace("-", "")
        if not names_city and len(mine) < 3:  # "Holy Cross" alone matched one in another state
            return None
        return root, entry, scored[0][0]


def hospitals(states: list[str] | None) -> pl.DataFrame:
    if not RAW_PATH.exists():
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            download(client, current_download_url(client)[0], RAW_PATH)
    raw = pl.read_csv(RAW_PATH, infer_schema_length=0).select(list(COLUMNS)).rename(COLUMNS)
    df = raw.filter(~pl.col("ownership").is_in(FEDERAL_OWNERSHIP))
    if states:
        df = df.filter(pl.col("state").is_in([s.upper() for s in states]))
    return df.sort("state", "ccn")


def dolthub_homepages(refresh: bool) -> dict[str, str]:
    """CCN -> homepage URL from DoltHub, fetched in pages of 1,000 and cached."""
    cache = OUT / "dolthub_homepages.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    found, offset = {}, 0
    with httpx.Client(timeout=60) as client:
        while True:
            q = ("SELECT cms_certification_num AS ccn, homepage_url FROM hospitals "
                 f"WHERE homepage_url IS NOT NULL ORDER BY ccn LIMIT 1000 OFFSET {offset}")  # fmt: skip
            rows = client.get(DOLTHUB, params={"q": q}).raise_for_status().json().get("rows", [])
            found |= {r["ccn"]: r["homepage_url"] for r in rows if r.get("homepage_url")}
            if len(rows) < 1000:
                break
            offset += 1000
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(found, indent=0, sort_keys=True))
    return found


def wikidata_hospitals(refresh: bool) -> list[dict]:
    """Rows of WIKIDATA_QUERY (item, itemLabel, website, stateCode, cityLabel), cached."""
    cache = OUT / "wikidata_hospitals.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    with httpx.Client(timeout=300, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(WIKIDATA, params={"query": WIKIDATA_QUERY, "format": "json"})
    rows = [{k: v["value"] for k, v in b.items()}
            for b in response.raise_for_status().json()["results"]["bindings"]]  # fmt: skip
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


class Websites:
    """Wikidata's hospitals by state, for a website by name."""

    def __init__(self, rows: list[dict]):
        self.by_state: dict[str, list[dict]] = {}
        for r in rows:
            state = r.get("stateCode", "").removeprefix("US-")
            if state and r.get("itemLabel") and site_root(r.get("website", "")):
                self.by_state.setdefault(state, []).append(r)

    def match(self, name: str, city: str, state: str) -> str | None:
        """The site root of a near-exact, unambiguous name match in the same state."""
        scored = sorted(((name_score(name, r["itemLabel"]), i)
                         for i, r in enumerate(self.by_state.get(state, []))), reverse=True)  # fmt: skip
        if not scored or scored[0][0] < 0.9:
            return None
        rows = self.by_state[state]
        top = [rows[i] for sc, i in scored if sc >= scored[0][0] - 0.05]
        if len({site_root(r["website"]) for r in top}) > 1:
            return None  # two hospitals of that name, or one with two websites
        names_city = city and any(r.get("cityLabel", "").upper() == city.upper() for r in top)
        if not names_city and len(words(name)) < 3:
            return None
        return site_root(top[0]["website"])


def site_root(url: str) -> str | None:
    """https://host for a homepage URL ("www.x.org/about" -> https://www.x.org)."""
    url = url.strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    return f"https://{host}" if "." in host else None


def fetch_all(roots: list[str], refresh: bool) -> dict[str, tuple[str, str]]:
    """root -> (status, text) of its cms-hpt.txt, cached one JSON file per host."""
    folder = OUT / "cms_hpt"
    folder.mkdir(parents=True, exist_ok=True)

    def one(root: str) -> tuple[str, tuple[str, str]]:
        path = folder / f"{urlparse(root).netloc}.json"
        if path.exists() and not refresh:
            cached = json.loads(path.read_text(encoding="utf-8"))
            return root, (cached["status"], cached["text"])
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as client:  # fmt: skip
            status, text = fetch(client, f"{root}/cms-hpt.txt")
        if status not in FOUND_STATUS:
            text = ""  # an error page is not worth keeping
        path.write_text(json.dumps({"status": status, "text": text[:2_000_000]}), encoding="utf-8")
        return root, (status, text)

    with ThreadPoolExecutor(THREADS) as pool:
        return dict(pool.map(one, roots))


def discover(states: list[str] | None = None, refresh: bool = False) -> pl.DataFrame:
    started = time.time()
    hosp = hospitals(states)
    homepages = dolthub_homepages(refresh)
    roots = {ccn: site_root(homepages.get(ccn, "")) for ccn in hosp["ccn"]}
    websites = Websites(wikidata_hospitals(refresh))
    sources = {ccn: "dolthub" for ccn, root in roots.items() if root}
    for h in hosp.filter(~pl.col("ccn").is_in(list(sources))).iter_rows(named=True):
        if root := websites.match(h["name"], h["city"], h["state"]):
            roots[h["ccn"]], sources[h["ccn"]] = root, "wikidata"
    fetched = fetch_all(sorted({r for r in roots.values() if r} | set(system_roots())), refresh)
    index = Index(fetched)

    rows = []
    for h in hosp.iter_rows(named=True):
        row = match_hospital(h, roots.get(h["ccn"]), fetched, index)
        rows.append(row | {"website_source": sources.get(h["ccn"], "")})
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = pl.DataFrame(rows, infer_schema_length=None).with_columns(
        pl.lit(checked_at).alias("checked_at")
    )
    out.write_parquet(OUT / "sources.parquet")
    print(f"{out.height:,} hospitals, {len(fetched):,} websites, {time.time() - started:.0f}s")
    return out


def match_hospital(h: dict, root: str | None, fetched: dict, index: Index) -> dict:
    """One sources row: its own website's file first, then any file (system_match)."""
    row = {"ccn": h["ccn"], "state": h["state"], "name": h["name"], "city": h["city"],
           "website": root or "", "status": "no_website", "location_name": "", "mrf_url": "",
           "source_page_url": "", "match_score": None}  # fmt: skip
    if root:
        status, text = fetched[root]
        if status in FOUND_STATUS and looks_like_price_file(text):
            return row | {"status": "found_malformed", "mrf_url": f"{root}/cms-hpt.txt"}
        row["status"] = status
        if status in FOUND_STATUS:
            entry, score = best_entry(h["name"], parse_cms_hpt(text), urlparse(root).netloc)
            if entry is not None and entry.get("mrf-url"):
                return row | {"status": FOUND_STATUS[status], "match_score": score,
                              "location_name": entry.get("location-name", ""),
                              "mrf_url": entry["mrf-url"],
                              "source_page_url": entry.get("source-page-url", "")}  # fmt: skip
            row |= {"status": "no_matching_location", "match_score": score}
    if (found := index.match(h["name"], h["city"])) is not None:
        system_root, entry, score = found
        return row | {"status": "system_match", "website": system_root, "match_score": score,
                      "location_name": entry["location-name"], "mrf_url": entry["mrf-url"],
                      "source_page_url": entry.get("source-page-url", "")}  # fmt: skip
    return row


def report(out: pl.DataFrame) -> None:
    found = pl.col("status").str.starts_with("found") | (pl.col("status") == "system_match")
    print(out["status"].value_counts(sort=True))
    by_state = (out.group_by("state").agg(pl.len().alias("hospitals"), found.sum().alias("found"))
                .with_columns((100 * pl.col("found") / pl.col("hospitals")).round(0).alias("pct"))
                .sort("pct"))  # fmt: skip
    print(by_state.head(10))
    print(f"found {out.filter(found).height:,} of {out.height:,} "
          f"({100 * out.filter(found).height / out.height:.0f}%)")  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", nargs="*", help="only these states (default: all)")
    parser.add_argument("--refresh", action="store_true", help="refetch everything")
    args = parser.parse_args()
    report(discover(args.state, args.refresh))


if __name__ == "__main__":
    main()
