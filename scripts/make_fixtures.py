"""Cut small test fixtures from the newest raw hospital files.

Usage:
    uv run python scripts/make_fixtures.py

Writes tests/fixtures/<ccn>.csv or .json: the metadata and header rows, up to 40 items
carrying a shoppable code (spread evenly through the file) and the first 10 that don't.
Values are copied unchanged, so each fixture keeps its file's quirks.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest.hospitals.parse import (
    PARSED_DIR,
    RAW_DIR,
    extract_zip,
    newest_file,
    normalize_header,
    open_text,
    sniff_format,
)

FIXTURES = Path("tests/fixtures")
MATCHING, OTHER = 40, 10
with open("warehouse/seeds/shoppable_services.csv", encoding="utf-8") as seed:
    SHOPPABLE = {
        row["code"].zfill(3) if row["code_type"] == "MS-DRG" else row["code"]
        for row in csv.DictReader(seed)
    }


def is_shoppable(code: str) -> bool:
    code = code.strip()
    return code in SHOPPABLE or code.zfill(3) in SHOPPABLE


def spread(rows: list, n: int) -> list:
    step = max(1, len(rows) // n)
    return rows[::step][:n]


def csv_fixture(path: Path, dest: Path) -> None:
    with open_text(path) as f:
        reader = csv.reader(f)
        meta_keys, meta_values, header = next(reader), next(reader), next(reader)
        code_idx = [
            i for i, h in enumerate(header) if re.fullmatch(r"code\|\d+", normalize_header(h))
        ]
        matching, other = [], []
        for row in reader:
            if any(i < len(row) and is_shoppable(row[i]) for i in code_idx):
                matching.append(row)
            elif len(other) < OTHER:
                other.append(row)
    with dest.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([meta_keys, meta_values, header,
                                 *spread(matching, MATCHING), *other])  # fmt: skip


def json_fixture(path: Path, dest: Path) -> None:
    with open_text(path) as f:
        doc = json.load(f)
    matching, other = [], []
    for item in doc["standard_charge_information"]:
        codes = item.get("code_information", [])
        if any(is_shoppable(str(c.get("code", ""))) for c in codes):
            matching.append(item)
        elif len(other) < OTHER:
            other.append(item)
    doc["standard_charge_information"] = spread(matching, MATCHING) + other
    dest.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ccn", nargs="*", help="only these hospitals")
    args = parser.parse_args()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    ccns = args.ccn or sorted({p.name.split("_")[0] for p in RAW_DIR.glob("*/*.gz")})
    for ccn in ccns:
        path = newest_file(ccn)
        fmt = sniff_format(path)
        if fmt == "zip":  # the fixture is the CSV or JSON inside; zip handling is unit-tested
            path = extract_zip(path, PARSED_DIR / "tmp")
            fmt = sniff_format(path)
        dest = FIXTURES / f"{ccn}.{fmt}"
        (json_fixture if fmt == "json" else csv_fixture)(path, dest)
        if path.parent.name == "tmp":
            path.unlink()
        print(f"{dest}  {dest.stat().st_size / 1024:,.0f} KB")


if __name__ == "__main__":
    main()
