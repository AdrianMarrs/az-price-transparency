"""Profile downloaded hospital price files: rows, payer-plans, and dollar vs. percentage prices.

Usage:
    uv run python scripts/profile_raw_files.py data/raw/<yyyy-mm-dd>

Exploration only (Phase 1 step 4); the numbers feed docs/01-hospitals.md. "dollar" is the
share of payer prices given as a dollar amount; the rest give only a percentage or an
algorithm (which includes "bundled into the DRG payment" rows).
"""

import gzip
import json
import sys
from pathlib import Path

import polars as pl


def present(col: str) -> pl.Expr:
    return pl.col(col).is_not_null() & (pl.col(col).str.strip_chars() != "")


def tally(dollar: pl.Expr, pct: pl.Expr, algo: pl.Expr) -> list[pl.Expr]:
    return [
        dollar.sum().alias("dollar"),
        (~dollar & (pct | algo)).sum().alias("pct_or_algo_only"),
    ]


def report(name, rows, payer_plans, dollar, other, codes):
    total = dollar + other
    share = f"{dollar / total:.0%}" if total else "-"
    print(
        f"{name[:45]:45} rows={rows:>9,} payer_plans={payer_plans:>4} "
        f"payer_prices={total:>10,} dollar={share:>4} code_types={codes}"
    )


for path in sorted(Path(sys.argv[1]).glob("*.gz")):
    name = path.name
    if ".json" in name:
        doc = json.loads(gzip.decompress(path.read_bytes()))
        items = doc["standard_charge_information"]
        dollar = other = 0
        plans, codes = set(), {}
        for item in items:
            for c in item.get("code_information", []):
                codes[c["type"]] = codes.get(c["type"], 0) + 1
            for sc in item.get("standard_charges", []):
                for p in sc.get("payers_information", []) or []:
                    plans.add((p.get("payer_name"), p.get("plan_name")))
                    if p.get("standard_charge_dollar") not in (None, ""):
                        dollar += 1
                    elif p.get("standard_charge_percentage") or p.get("standard_charge_algorithm"):
                        other += 1
        top = dict(sorted(codes.items(), key=lambda kv: -kv[1])[:5])
        report(name, len(items), len(plans), dollar, other, top)
        continue

    df = pl.read_csv(path, skip_rows=2, infer_schema_length=0, truncate_ragged_lines=True)
    df = df.rename({c: c.replace(" ", "") for c in df.columns})
    type_cols = [c for c in df.columns if c.startswith("code|") and c.endswith("|type")]
    codes = (
        pl.concat([df.select(pl.col(c).alias("t")) for c in type_cols])
        .filter(present("t"))["t"]
        .value_counts(sort=True)
        .head(5)
    )
    code_summary = dict(zip(codes["t"], codes["count"]))
    if "payer_name" in df.columns:  # tall
        payers = df.filter(present("payer_name"))
        r = payers.select(
            tally(
                present("standard_charge|negotiated_dollar"),
                present("standard_charge|negotiated_percentage"),
                present("standard_charge|negotiated_algorithm"),
            )
        )
        n_plans = payers.select(pl.struct("payer_name", "plan_name").n_unique()).item()
        report(
            name, df.height, n_plans, r["dollar"].item(), r["pct_or_algo_only"].item(), code_summary
        )
    else:  # wide
        prefixes = sorted(
            {c.rsplit("|", 1)[0] for c in df.columns if c.endswith("|negotiated_dollar")}
        )
        dollar = other = 0
        for p in prefixes:
            r = df.select(
                tally(
                    present(f"{p}|negotiated_dollar"),
                    present(f"{p}|negotiated_percentage"),
                    present(f"{p}|negotiated_algorithm"),
                )
            )
            dollar += r["dollar"].item()
            other += r["pct_or_algo_only"].item()
        report(name, df.height, len(prefixes), dollar, other, code_summary)
