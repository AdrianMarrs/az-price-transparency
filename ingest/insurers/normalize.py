"""Flatten kept Transparency in Coverage rates (JSON Lines) into Parquet rows.

Usage:
    uv run python -m ingest.insurers.normalize [--insurer cigna] [--month 2026-10]

Reads data/insurers/raw/insurer=<name>/month=<m>/*.jsonl.gz (written by ingest.insurers.tic)
and writes data/insurers/parquet/insurer=<name>/month=<m>/<network>.parquet: one row per
hospital (CCN) x negotiated price. A price that applies to several of a hospital's provider
groups appears once. Lists (service codes, modifiers) become comma-separated text, sorted,
so equal prices compare equal. Copied to the data bucket when DATA_BUCKET is set.
"""

import argparse
import gzip
import json
import re
from collections.abc import Iterator
from pathlib import Path

import polars as pl

from ingest.insurers.tic import RAW_DIR
from ingest.storage import upload

PARQUET_DIR = Path("data/insurers/parquet")

SCHEMA = {
    "insurer": pl.String,
    "network": pl.String,
    "month": pl.String,
    "ccn": pl.String,
    "billing_code_type": pl.String,
    "billing_code": pl.String,
    "description": pl.String,
    "negotiation_arrangement": pl.String,
    "negotiated_type": pl.String,
    "negotiated_rate": pl.Float64,
    "billing_class": pl.String,
    "setting": pl.String,
    "service_codes": pl.String,
    "modifiers": pl.String,
    "expiration_date": pl.String,
}


def network_name(path: Path) -> str:
    """The network part of an in-network file's name, without the date and the insurer:

    2026-10-01_cigna-health-life-insurance-company_arizona-hmo_in-network-rates -> arizona-hmo
    2026-10-01_sagamorehn_cigna_in-network-rates (a partner's file)  -> sagamorehn_cigna
    2026_10_01_priority_health_PPO_in-network-rates                   -> priority_health_PPO
    """
    stem = path.name.removesuffix(".jsonl.gz")
    m = re.match(r"\d{4}[-_]\d{2}[-_]\d{2}_(.+)_in-network-rates$", stem)
    if not m:
        return stem
    entity, _, rest = m.group(1).partition("_")
    return rest if rest and entity.endswith("-company") else m.group(1)


def joined(values) -> str | None:
    return ",".join(sorted(str(v) for v in values)) if values else None


def rows(line: dict, insurer: str, network: str, month: str) -> Iterator[dict]:
    """Flat rows for one billing code."""
    base = {
        "insurer": insurer, "network": network, "month": month,
        "billing_code_type": line.get("billing_code_type"),
        "billing_code": str(line.get("billing_code")),
        "description": line.get("description") or line.get("name"),
        "negotiation_arrangement": line.get("negotiation_arrangement"),
    }  # fmt: skip
    for rate in line.get("negotiated_rates", []):
        for price in rate.get("negotiated_prices", []):
            flat = base | {
                "negotiated_type": price.get("negotiated_type"),
                "negotiated_rate": price.get("negotiated_rate"),
                "billing_class": price.get("billing_class"),
                "setting": price.get("setting"),
                "service_codes": joined(price.get("service_code")),
                "modifiers": joined(price.get("billing_code_modifier")),
                "expiration_date": price.get("expiration_date"),
            }
            for ccn in rate.get("ccns", []):
                yield flat | {"ccn": ccn}


def normalize_file(path: Path, insurer: str, month: str) -> pl.DataFrame:
    network = network_name(path)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        records = [r for line in f for r in rows(json.loads(line), insurer, network, month)]
    df = (
        pl.DataFrame(records, schema=SCHEMA, orient="row")
        if records
        else pl.DataFrame(schema=SCHEMA)
    )
    return df.unique(maintain_order=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--insurer", default="cigna")
    parser.add_argument("--month", required=True)
    args = parser.parse_args()
    src = RAW_DIR / f"insurer={args.insurer}" / f"month={args.month}"
    out_dir = PARQUET_DIR / f"insurer={args.insurer}" / f"month={args.month}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.glob("*.jsonl.gz")):
        df = normalize_file(path, args.insurer, args.month)
        dest = out_dir / f"{network_name(path)}.parquet"
        df.write_parquet(dest)
        uploaded = upload(dest)
        print(f"{network_name(path):<45} {df.height:>10,} rows  "
              f"{df['ccn'].n_unique():>3} hospitals  {uploaded or dest}")  # fmt: skip


if __name__ == "__main__":
    main()
