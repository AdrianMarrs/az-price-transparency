"""Cut small test fixtures from the newest raw hospital files.

Usage:
    uv run python scripts/make_fixtures.py

Writes tests/fixtures/<ccn>.csv or .json: the metadata and header rows, up to 40 items
carrying a shoppable code (spread evenly through the file) and the first 10 that don't.
Values are copied unchanged, so each fixture keeps its file's quirks.
"""

import csv
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest.hospitals.parse import RAW_DIR, newest_file, normalize_header

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
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
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
    doc = json.loads(gzip.decompress(path.read_bytes()))
    items = doc["standard_charge_information"]
    matching = [
        i
        for i in items
        if any(is_shoppable(str(c.get("code", ""))) for c in i.get("code_information", []))
    ]
    other = [i for i in items if i not in matching][:OTHER]
    doc["standard_charge_information"] = spread(matching, MATCHING) + other
    dest.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for ccn in sorted({p.name.split("_")[0] for p in RAW_DIR.glob("*/*.gz")}):
        path = newest_file(ccn)
        dest = FIXTURES / f"{ccn}.{'json' if '.json' in path.name else 'csv'}"
        (json_fixture if dest.suffix == ".json" else csv_fixture)(path, dest)
        print(f"{dest}  {dest.stat().st_size / 1024:,.0f} KB")


if __name__ == "__main__":
    main()
