"""Parse a hospital price file into one long, validated table of service prices.

Usage:
    uv run python -m ingest.hospitals.parse [--ccn 030006 ...]

For each hospital, takes its newest file under data/raw/ and writes
data/parsed/<ccn>.parquet (valid prices) and data/parsed/<ccn>_rejects.csv (rows that
failed validation, with the reason). Handles the three CMS template shapes:

- CSV tall: one row per item x payer x plan (payer_name, plan_name columns)
- CSV wide: one row per item, a column group per payer and plan
- JSON: items with code_information and standard_charges[].payers_information[]

Only items carrying a service code are kept: a CPT code (procedures, tests, imaging,
visits), a HCPCS G code, or an MS-DRG (inpatient stays). Supplies, devices, drugs and
hospital-internal codes are dropped. The 70 CMS-specified shoppable services are flagged
in cms_shoppable_id. The columns that change a price (setting, billing class, modifiers,
payer, plan, methodology) are never dropped. See docs/01-hospitals.md for the quirks.

Validation runs as polars expressions over all rows (fast); PriceRow, the pydantic model,
is the readable specification of the same rules, and tests check that the two agree.
"""

import argparse
import csv
import gzip
import io
import json
import re
import traceback
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, ValidationError, field_validator, model_validator

RAW_DIR = Path("data/raw")
PARSED_DIR = Path("data/parsed")
# Files are read whole into memory. Larger ones are recorded as deferred until there is a
# streaming parser; JSON expands far more in memory than CSV, so its limit is lower.
MAX_CSV_BYTES = 3 * 10**9
MAX_JSON_BYTES = 6 * 10**8
SHOPPABLE_PATH = Path("warehouse/seeds/shoppable_services.csv")

# CSV column (after header normalization) -> our column name
ITEM_COLUMNS = {
    "description": "description",
    "setting": "setting",
    "billing_class": "billing_class",
    "modifiers": "modifiers",
    "standard_charge|gross": "gross",
    "standard_charge|discounted_cash": "discounted_cash",
    "standard_charge|min": "min",
    "standard_charge|max": "max",
}
PAYER_FIELDS = {
    "negotiated_dollar": "negotiated_dollar",
    "negotiated_percentage": "negotiated_percentage",
    "negotiated_algorithm": "negotiated_algorithm",
    "methodology": "methodology",
}
ITEM_PRICES = ["gross", "discounted_cash", "min", "max"]
PAYER_PRICES = ["negotiated_dollar", "negotiated_percentage"]
KEYS = ["description", "code", "code_type", "cms_shoppable_id", "setting", "billing_class",
        "modifiers"]  # fmt: skip
OUTPUT_COLUMNS = [*KEYS, "payer_name", "plan_name", "methodology", "price_type", "amount",
                  "algorithm"]  # fmt: skip

PriceType = Literal[
    "gross", "discounted_cash", "min", "max",
    "negotiated_dollar", "negotiated_percentage", "negotiated_algorithm",
]  # fmt: skip
Methodology = Literal[
    "case rate", "fee schedule", "percent of total billed charges", "per diem", "other"
]
SETTINGS = ["inpatient", "outpatient", "both"]
METHODOLOGIES = list(Methodology.__args__)


# ---------- headers and metadata ----------


def normalize_header(header: str) -> str:
    """'standard_charge|[payer_AETNA ]|[plan_ HMO/PPO]|negotiated_dollar ' ->
    'standard_charge|AETNA|HMO/PPO|negotiated_dollar'. Field names are lowercased;
    payer and plan names keep their case."""
    parts = [p.strip() for p in header.replace("\ufeff", "").split("|")]
    parts = [re.sub(r"^\[(payer|plan)_\s*|\s*\]$", "", p).strip() for p in parts]
    parts[0] = parts[0].lower()
    if parts[0] in {"standard_charge", "code"} or len(parts) <= 2:
        parts[-1] = parts[-1].lower()
    return "|".join(parts)


def parse_date(value: str | None) -> date | None:
    """'2026-04-01', '    2026-04-01', '7/31/2026' and '12/31/2025' all parse."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def open_text(path: Path) -> io.TextIOBase:
    """Open a raw (.gz) or plain file as text; callers use it in a with-block."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open(encoding="utf-8-sig", newline="")


def read_csv_metadata(path: Path) -> dict:
    """Rows 1-2 of a CMS CSV: header names, then values. Extra fields are tolerated."""
    with open_text(path) as f:
        reader = csv.reader(f)
        keys, values = next(reader), next(reader)
    meta = {normalize_header(k): v.strip() for k, v in zip(keys, values) if k.strip()}
    return {
        "hospital_name": meta.get("hospital_name"),
        "last_updated_on": parse_date(meta.get("last_updated_on")),
        "version": meta.get("version"),
        # Header names as given (the attestation's name is its long text), for compliance.
        "header_fields": sorted(k[:40] for k, v in meta.items() if v),
    }


# ---------- reading each shape into an item table ----------


def read_csv_with_python(path: Path) -> pl.DataFrame:
    """Slower fallback for files polars' parallel reader rejects (e.g. Kingman Regional:
    'CSV malformed: expected 3024 rows, actual 3168 rows', from line breaks inside values)."""
    with open_text(path) as f:
        reader = csv.reader(f)
        next(reader), next(reader)
        header = next(reader)
        width = len(header)
        rows = [(row + [""] * width)[:width] for row in reader]
    names = [h if h.strip() else f"_duplicated_blank_{i}" for i, h in enumerate(header)]
    seen: dict[str, int] = {}
    for i, name in enumerate(names):  # pl.DataFrame needs unique names; read_csv_items renames
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            names[i] = f"{name}_duplicated_{seen[name] - 1}"
    return pl.DataFrame(rows, schema=names, orient="row").with_columns(pl.all().replace("", None))


def read_csv_items(path: Path) -> pl.DataFrame:
    try:
        df = pl.read_csv(path, skip_rows=2, infer_schema_length=0, truncate_ragged_lines=True)
    except pl.exceptions.ComputeError:
        df = read_csv_with_python(path)
    names, seen = [], set()
    for column in df.columns:
        name = normalize_header(column)
        while name in seen:  # rare duplicates after normalization
            name += "_dup"
        seen.add(name)
        names.append(name)
    df.columns = names
    return df.select([c for c in df.columns if c and not c.startswith("_duplicated")])


def json_items(doc: dict) -> pl.DataFrame:
    """Flatten JSON into the tall CSV layout (one row per item x payer x plan)."""
    rows = []
    for item in doc.get("standard_charge_information", []):
        codes = {}
        for i, c in enumerate(item.get("code_information", []), 1):
            codes[f"code|{i}"], codes[f"code|{i}|type"] = str(c.get("code", "")), c.get("type")
        for sc in item.get("standard_charges", []):
            base = {
                **codes,
                "description": item.get("description"),
                "setting": sc.get("setting"),
                "billing_class": sc.get("billing_class"),
                "modifiers": "|".join(sc.get("modifier_code") or []) or None,
                "standard_charge|gross": sc.get("gross_charge"),
                "standard_charge|discounted_cash": sc.get("discounted_cash"),
                "standard_charge|min": sc.get("minimum"),
                "standard_charge|max": sc.get("maximum"),
            }
            payers = sc.get("payers_information") or [{}]
            for p in payers:
                rows.append({
                    **base,
                    "payer_name": p.get("payer_name"),
                    "plan_name": p.get("plan_name"),
                    "standard_charge|negotiated_dollar": p.get("standard_charge_dollar"),
                    "standard_charge|negotiated_percentage": p.get("standard_charge_percentage"),
                    "standard_charge|negotiated_algorithm": p.get("standard_charge_algorithm"),
                    "standard_charge|methodology": p.get("methodology"),
                })  # fmt: skip
    df = pl.DataFrame(rows, infer_schema_length=None)
    return df.select(pl.all().cast(pl.String))


def read_json(path: Path) -> tuple[dict, pl.DataFrame]:
    with open_text(path) as f:
        doc = json.load(f)
    meta = {
        "hospital_name": doc.get("hospital_name"),
        "last_updated_on": parse_date(doc.get("last_updated_on")),
        "version": doc.get("version"),
        "header_fields": sorted(k for k, v in doc.items()
                                if v and k != "standard_charge_information"),
    }  # fmt: skip
    return meta, json_items(doc)


# ---------- service codes ----------


CODE_FAMILIES = {"CPT": "CPT/HCPCS", "HCPCS": "CPT/HCPCS", "MSDRG": "MS-DRG"}
# CPT Level I codes are five digits; HCPCS G codes are procedures and services. Other
# HCPCS letters are supplies (A, C, E, K, L), drugs (J) and miscellaneous codes.
SERVICE_CODE = r"^(\d{5}|G\d{4})$"


def code_family(column: str) -> pl.Expr:
    """'CPT', 'hcpcs', 'MS-DRG', 'MS DRG' -> 'CPT/HCPCS' or 'MS-DRG'; anything else null."""
    return (
        pl.col(column)
        .str.to_uppercase()
        .str.replace_all(r"[\s-]", "")
        .replace_strict(CODE_FAMILIES, default=None, return_dtype=pl.String)
    )


def match_codes(items: pl.DataFrame, shoppable: pl.DataFrame) -> pl.DataFrame:
    """row_idx -> (code, code_type, cms_shoppable_id) for items carrying a service code.

    cms_shoppable_id is set when the code is one of CMS's 70 shoppable services."""
    numbers = sorted(
        {int(m.group(1)) for c in items.columns if (m := re.match(r"code\|(\d+)$", c))}
    )
    if not numbers:
        return pl.DataFrame(schema={"row_idx": pl.UInt32, "code": pl.String,
                                    "code_type": pl.String,
                                    "cms_shoppable_id": pl.Int64})  # fmt: skip
    codes = pl.concat(
        [
            items.select(
                "row_idx",
                pl.col(f"code|{n}").str.strip_chars().alias("code"),
                code_family(f"code|{n}|type").alias("code_type")
                if f"code|{n}|type" in items.columns
                else pl.lit(None, pl.String).alias("code_type"),
            )
            for n in numbers
        ]
    ).filter(pl.col("code_type").is_not_null() & pl.col("code").is_not_null())
    codes = codes.with_columns(
        pl.when(pl.col("code_type") == "MS-DRG")
        .then(pl.col("code").str.zfill(3))
        .otherwise(pl.col("code").str.to_uppercase())
        .alias("code")
    )
    codes = codes.filter(
        (pl.col("code_type") == "MS-DRG") | pl.col("code").str.contains(SERVICE_CODE)
    )
    return codes.join(shoppable, on=["code", "code_type"], how="left").unique(["row_idx", "code"])


# ---------- to long price rows ----------


def present(column: str) -> pl.Expr:
    return pl.col(column).is_not_null() & (pl.col(column).str.strip_chars() != "")


def ensure(df: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    missing = [pl.lit(None, pl.String).alias(c) for c in columns if c not in df.columns]
    return df.with_columns(missing) if missing else df


def payer_rows_wide(matched: pl.DataFrame) -> pl.DataFrame:
    """One row per item x payer x plan from the wide layout's column groups."""
    groups: dict[tuple[str, str], dict[str, str]] = {}
    for column in matched.columns:
        parts = column.split("|")
        if len(parts) == 4 and parts[0] == "standard_charge" and parts[3] in PAYER_FIELDS:
            groups.setdefault((parts[1], parts[2]), {})[PAYER_FIELDS[parts[3]]] = column
    frames = []
    for (payer, plan), columns in groups.items():
        frame = matched.select(
            *KEYS,
            pl.lit(payer).alias("payer_name"),
            pl.lit(plan).alias("plan_name"),
            *[pl.col(src).alias(dst) for dst, src in columns.items()],
        )
        frames.append(ensure(frame, list(PAYER_FIELDS.values())))
    if not frames:
        return ensure(matched.select(KEYS).clear(), ["payer_name", "plan_name",
                                                     *PAYER_FIELDS.values()])  # fmt: skip
    return pl.concat(frames, how="diagonal")


def to_long(items: pl.DataFrame, shoppable: pl.DataFrame) -> pl.DataFrame:
    items = ensure(items.with_row_index("row_idx"), list(ITEM_COLUMNS))
    matched = items.join(match_codes(items, shoppable), on="row_idx")
    matched = matched.rename({src: dst for src, dst in ITEM_COLUMNS.items()})

    item_prices = (
        matched.select(*KEYS, *ITEM_PRICES)
        .unpivot(index=KEYS, on=ITEM_PRICES, variable_name="price_type", value_name="amount")
        .filter(present("amount"))
        .unique()
    )

    if "payer_name" in matched.columns:  # tall CSV or JSON
        payers = matched.select(
            *KEYS, "payer_name", "plan_name",
            *[pl.col(f"standard_charge|{f}").alias(f) if f"standard_charge|{f}" in matched.columns
              else pl.lit(None, pl.String).alias(f) for f in PAYER_FIELDS],
        ).filter(present("payer_name"))  # fmt: skip
    else:
        payers = payer_rows_wide(matched)

    payer_prices = payers.unpivot(
        index=[*KEYS, "payer_name", "plan_name", "methodology", "negotiated_algorithm"],
        on=PAYER_PRICES, variable_name="price_type", value_name="amount",
    ).filter(present("amount"))  # fmt: skip
    algorithm_only = payers.filter(
        ~present("negotiated_dollar") & ~present("negotiated_percentage")
        & present("negotiated_algorithm")
    ).select(
        *KEYS, "payer_name", "plan_name", "methodology", "negotiated_algorithm",
        pl.lit("negotiated_algorithm").alias("price_type"), pl.lit(None, pl.String).alias("amount"),
    )  # fmt: skip

    payer_long = pl.concat([payer_prices, algorithm_only], how="diagonal").rename(
        {"negotiated_algorithm": "algorithm"}
    )
    return pl.concat([item_prices, payer_long], how="diagonal").select(OUTPUT_COLUMNS)


# ---------- validation ----------


class PriceRow(BaseModel):
    """The rules one price row must meet, written out readably. validate() applies the
    same rules to whole columns at once; tests check that both accept the same rows."""

    description: str
    code: str
    code_type: Literal["CPT/HCPCS", "MS-DRG"]
    cms_shoppable_id: int | None = None
    setting: Literal["inpatient", "outpatient", "both"]
    billing_class: str | None = None
    modifiers: str | None = None
    payer_name: str | None = None
    plan_name: str | None = None
    methodology: Methodology | None = None
    price_type: PriceType
    amount: Decimal | None = None
    algorithm: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        if isinstance(v, str):
            v = " ".join(v.split())  # also removes stray \r\n
            return v or None
        return v

    @field_validator("setting", "methodology", "billing_class", mode="before")
    @classmethod
    def lowercase(cls, v):
        return v.lower() if isinstance(v, str) else v

    @field_validator("amount", mode="before")
    @classmethod
    def clean_amount(cls, v):
        if v is None:
            return None
        try:
            return Decimal(str(v).replace("$", "").replace(",", "").replace("%", "").strip())
        except InvalidOperation:
            raise ValueError(f"not a number: {v!r}") from None

    @model_validator(mode="after")
    def check_rules(self):
        if self.amount is not None and self.amount < 0:
            raise ValueError("negative amount")
        if self.price_type.startswith("negotiated") and not self.payer_name:
            raise ValueError("negotiated price without a payer")
        if self.price_type != "negotiated_algorithm" and self.amount is None:
            raise ValueError("missing amount")
        if self.price_type == "negotiated_algorithm" and not self.algorithm:
            raise ValueError("algorithm price without algorithm text")
        return self


def pydantic_reason(row: dict) -> str | None:
    """None if PriceRow accepts the row, else its error message (used by tests)."""
    try:
        PriceRow(**row)
        return None
    except ValidationError as e:
        return "; ".join(err["msg"] for err in e.errors())


def clean(long: pl.DataFrame) -> pl.DataFrame:
    """Collapse whitespace (incl. stray \\r\\n), blank -> null, lowercase the coded fields,
    and parse amounts ('$1,234.50', '60%') into numbers."""
    text = [c for c in OUTPUT_COLUMNS if c != "cms_shoppable_id"]
    df = long.with_columns(
        pl.col(c).cast(pl.String).str.replace_all(r"\s+", " ").str.strip_chars()
        .replace("", None).alias(c)
        for c in text
    ).with_columns(
        pl.col("setting", "methodology", "billing_class").str.to_lowercase(),
        pl.col("amount").str.replace_all(r"[$,%]", "").str.strip_chars().alias("amount"),
    )  # fmt: skip
    return df.with_columns(pl.col("amount").cast(pl.Float64, strict=False).alias("number"))


def reject_reason() -> pl.Expr:
    """PriceRow's rules as one expression: '' for a valid row, else the reasons."""
    number, price_type = pl.col("number"), pl.col("price_type")
    rules = [
        (pl.col("description").is_null(), "description: missing"),
        (~pl.col("setting").is_in(SETTINGS).fill_null(False),
         "setting: not inpatient, outpatient or both"),
        (pl.col("methodology").is_not_null() & ~pl.col("methodology").is_in(METHODOLOGIES),
         "methodology: unknown value"),
        (pl.col("amount").is_not_null() & (number.is_null() | ~number.is_finite()),
         "amount: not a number"),
        (number < 0, "negative amount"),
        (price_type.str.starts_with("negotiated") & pl.col("payer_name").is_null(),
         "negotiated price without a payer"),
        ((price_type != "negotiated_algorithm") & pl.col("amount").is_null(), "missing amount"),
        ((price_type == "negotiated_algorithm") & pl.col("algorithm").is_null(),
         "algorithm price without algorithm text"),
    ]  # fmt: skip
    return pl.concat_str(
        [pl.when(rule.fill_null(False)).then(pl.lit(message)) for rule, message in rules],
        separator="; ",
        ignore_nulls=True,
    ).fill_null("")


def validate(long: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(valid rows, rejected rows with a reason)."""
    checked = clean(long).with_columns(reject_reason().alias("reason"))
    valid = checked.filter(pl.col("reason") == "").with_columns(
        pl.col("number").round(4).cast(pl.Decimal(18, 4)).alias("amount")
    )
    rejects = checked.filter(pl.col("reason") != "")
    return valid.select(OUTPUT_COLUMNS), rejects.select(*OUTPUT_COLUMNS, "reason")


# ---------- entry points ----------


def load_shoppable(path: Path = SHOPPABLE_PATH) -> pl.DataFrame:
    return (
        pl.read_csv(path, schema_overrides={"code": pl.String})
        .select("code", "code_type", pl.col("service_id").alias("cms_shoppable_id"))
        .unique(["code", "code_type"])
    )


def sniff_format(path: Path) -> str:
    """'zip', 'json' or 'csv' from the file's first bytes (many URLs have no extension)."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        head = f.read(4096)
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    return "json" if text[:1] in (b"{", b"[") else "csv"


def original_size(path: Path) -> int:
    """Uncompressed size of a .gz file from its trailer (exact below 4 GiB)."""
    if path.suffix != ".gz":
        return path.stat().st_size
    with path.open("rb") as f:
        f.seek(-4, 2)
        return int.from_bytes(f.read(4), "little")


def extract_zip(path: Path, work_dir: Path) -> Path:
    """Extract the largest CSV or JSON member of a (possibly gzipped) zip file."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f, zipfile.ZipFile(io.BytesIO(f.read())) as z:
        members = [m for m in z.infolist() if m.filename.lower().endswith((".csv", ".json"))]
        if not members:
            raise ValueError("zip file contains no CSV or JSON file")
        member = max(members, key=lambda m: m.file_size)
        work_dir.mkdir(parents=True, exist_ok=True)
        dest = work_dir / f"{path.name.split('.')[0]}_{Path(member.filename).name}"
        dest.write_bytes(z.read(member))
        return dest


def file_payer_counts(items: pl.DataFrame) -> dict[str, int]:
    """Insurer prices in the whole file, every code included (for compliance rules):
    how many there are, how many give a dollar amount, how many are 'bundled'."""
    if "payer_name" in items.columns:  # tall CSV or JSON
        groups = [("standard_charge|negotiated_dollar", "standard_charge|negotiated_percentage",
                   "standard_charge|negotiated_algorithm", present("payer_name"))]  # fmt: skip
    else:
        prefixes = {c.rsplit("|", 1)[0] for c in items.columns
                    if c.startswith("standard_charge|") and c.count("|") == 3}  # fmt: skip
        groups = [(f"{p}|negotiated_dollar", f"{p}|negotiated_percentage",
                   f"{p}|negotiated_algorithm", pl.lit(True)) for p in sorted(prefixes)]  # fmt: skip
    counts = {"file_payer_prices": 0, "file_payer_dollar": 0, "file_payer_bundled": 0}
    for dollar, pct, algo, has_payer in groups:
        has = {c: present(c) if c in items.columns else pl.lit(False) for c in (dollar, pct, algo)}
        bundled = has[algo] & pl.col(algo).str.contains("(?i)bundled") if algo in items.columns \
            else pl.lit(False)  # fmt: skip
        row = items.select(
            (has_payer & (has[dollar] | has[pct] | has[algo])).sum().alias("file_payer_prices"),
            (has_payer & has[dollar]).sum().alias("file_payer_dollar"),
            (has_payer & ~has[dollar] & bundled).sum().alias("file_payer_bundled"),
        ).row(0, named=True)
        for key in counts:
            counts[key] += row[key] or 0
    return counts


def parse_file(path: Path, shoppable: pl.DataFrame) -> tuple[dict, pl.DataFrame, pl.DataFrame]:
    """(metadata incl. counts, valid prices, rejects) for one raw file."""
    fmt = sniff_format(path)
    if fmt == "zip":
        extracted = extract_zip(path, PARSED_DIR / "tmp")
        try:
            return parse_file(extracted, shoppable)
        finally:
            extracted.unlink()
    if fmt == "json":
        meta, items = read_json(path)
    else:
        meta, items = read_csv_metadata(path), read_csv_items(path)
    meta["shape"] = "json" if fmt == "json" else (
        "tall" if "payer_name" in items.columns else "wide")  # fmt: skip
    meta["items"] = items.height
    meta |= file_payer_counts(items)
    long = to_long(items, shoppable)
    # Chargemaster lines that differ only by the hospital's internal item number collapse
    # to identical rows once that number is dropped; keep one.
    unique = long.unique(maintain_order=True)
    valid, rejects = validate(unique)
    # Cleaning can make more rows identical ("536.13" vs "536.130", extra spaces), which
    # dbt's unique price_id test caught statewide; drop those too.
    valid = valid.unique(maintain_order=True)
    meta |= {
        "price_rows": long.height,
        "duplicates": long.height - valid.height - rejects.height,
        "valid": valid.height,
        "rejected": rejects.height,
    }
    return meta, valid, rejects


def newest_file(ccn: str) -> Path | None:
    files = sorted(RAW_DIR.glob(f"*/{ccn}_*.gz"), key=lambda p: p.parent.name)
    return files[-1] if files else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ccn", nargs="*", help="only these hospitals")
    args = parser.parse_args()

    shoppable = load_shoppable()
    ccns = args.ccn or sorted({p.name.split("_")[0] for p in RAW_DIR.glob("*/*.gz")})
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    report = []
    for ccn in ccns:
        path = newest_file(ccn)
        if path is None:
            print(f"{ccn}  no raw file")
            continue
        entry = parse_one(ccn, path, shoppable)
        report.append(entry)
        print(f"{ccn}  {entry['outcome']:17} {entry.get('shape') or '':5} "
              f"items={entry.get('items') or 0:>9,}  prices={entry.get('valid') or 0:>9,}  "
              f"rejected={entry.get('rejected') or 0:>6,}  {entry.get('error') or ''}")  # fmt: skip

    print(update_report(report)["outcome"].value_counts(sort=True))


def update_report(entries: list[dict]) -> pl.DataFrame:
    """Write these entries into data/parsed/parse_report.csv, replacing the same hospitals'
    earlier rows and keeping everyone else's (a --ccn run doesn't drop other outcomes)."""
    report_path = PARSED_DIR / "parse_report.csv"
    new = pl.DataFrame(entries, infer_schema_length=None).cast(pl.String)
    if report_path.exists():
        old = pl.read_csv(report_path, infer_schema_length=0)
        new = pl.concat(
            [old.filter(~pl.col("ccn").is_in(new["ccn"].to_list())), new], how="diagonal"
        )
    new = new.sort("ccn")
    new.write_csv(report_path)
    return new


def outcome(meta: dict) -> str:
    """parsed / partly_parsed / no_service_codes / all_rejected, from the parse counts."""
    if meta["valid"] == 0:
        return "all_rejected" if meta["rejected"] else "no_service_codes"
    rejected_share = meta["rejected"] / (meta["valid"] + meta["rejected"])
    return "partly_parsed" if rejected_share >= 0.05 else "parsed"


def parse_one(ccn: str, path: Path, shoppable: pl.DataFrame) -> dict:
    """Parse one hospital's newest file and write its outputs; never raises."""
    entry = {"ccn": ccn, "path": path.as_posix(), "format": sniff_format(path)}
    size = original_size(path)
    limit = MAX_JSON_BYTES if entry["format"] == "json" else MAX_CSV_BYTES
    if size > limit:
        return entry | {"outcome": "deferred_too_large",
                        "error": f"{size / 1e9:.1f} GB; needs a streaming parser"}  # fmt: skip
    try:
        meta, valid, rejects = parse_file(path, shoppable)
    except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
        last = traceback.format_exception_only(e)[-1].strip()
        return entry | {"outcome": "failed", "error": last[:300]}
    valid.with_columns(
        pl.lit(ccn).alias("ccn"), pl.lit(path.as_posix()).alias("source_path")
    ).write_parquet(PARSED_DIR / f"{ccn}.parquet")
    rejects.write_csv(PARSED_DIR / f"{ccn}_rejects.csv")
    top_reason = rejects["reason"].mode().first() if rejects.height else None
    kinds = valid.select(
        (pl.col("price_type") == "negotiated_dollar").sum().alias("n_dollar"),
        (pl.col("price_type") == "negotiated_percentage").sum().alias("n_percentage"),
        ((pl.col("price_type") == "negotiated_algorithm")
         & ~pl.col("algorithm").str.contains("(?i)bundled").fill_null(False))
        .sum().alias("n_algorithm"),
        pl.col("algorithm").str.contains("(?i)bundled").fill_null(False).sum().alias("n_bundled"),
    ).row(0, named=True)  # fmt: skip
    return (
        entry
        | kinds
        | {
            "outcome": outcome(meta),
            "shape": meta["shape"],
            "version": meta.get("version"),
            "last_updated_on": meta.get("last_updated_on"),
            "header_fields": ";".join(meta.get("header_fields", [])),
            "items": meta["items"],
            "price_rows": meta["price_rows"],
            "duplicates": meta["duplicates"],
            "valid": meta["valid"],
            "rejected": meta["rejected"],
            "codes": valid["code"].n_unique(),
            "cms70": valid["cms_shoppable_id"].drop_nulls().n_unique(),
            "top_reject_reason": top_reason,
            "file_payer_prices": meta["file_payer_prices"],
            "file_payer_dollar": meta["file_payer_dollar"],
            "file_payer_bundled": meta["file_payer_bundled"],
        }
    )


if __name__ == "__main__":
    main()
