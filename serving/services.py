"""The service list: every service at least one hospital prices, with plain-English search
terms, as the site searches it (data/<state>/search.json, written by export_static.py).
"""

import csv
import os
import re
from pathlib import Path

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://pt:pt@localhost:5432/prices")
SEARCH_TERMS_PATH = Path(__file__).resolve().parents[1] / "warehouse/seeds/service_search_terms.csv"


def compact(value):
    """Drop null attributes: they cost bytes and the site treats a missing one as null."""
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def service_id(service_key: str) -> str:
    """The URL-safe id for a service: CPT/HCPCS:73721 -> cpt-hcpcs:73721."""
    return service_key.replace("/", "-").lower()


def load_search_terms(path: Path = SEARCH_TERMS_PATH) -> list[tuple[str, re.Pattern, str]]:
    """(match_on, pattern, terms) rows from the reviewed seed."""
    with path.open(newline="", encoding="utf-8") as f:
        return [(r["match_on"], re.compile(r["pattern"], re.IGNORECASE), r["terms"])
                for r in csv.DictReader(f)]  # fmt: skip


def search_terms(code: str, text: str, rules: list[tuple[str, re.Pattern, str]]) -> str | None:
    """Plain-English words for a service, so "knee mri" finds "MRI EXT LOWER JT"."""
    words = []
    for match_on, pattern, terms in rules:
        if pattern.search(code if match_on == "code" else text):
            words += [w for w in terms.split() if w not in words]
    return " ".join(words) or None


def services_list(conn: psycopg.Connection) -> list[dict]:
    """Every service at least one hospital prices, for search (data/<state>/search.json)."""
    rules = load_search_terms()
    rows = conn.execute("""
        SELECT service_key, code, code_type, common_description, cms_shoppable_id,
               cms_description, hospitals
        FROM marts.dim_services WHERE hospitals > 0 ORDER BY service_key""").fetchall()
    return [compact({"id": service_id(key), "key": key, "code": code, "code_type": code_type,
                     "description": description, "cms_shoppable_id": shoppable,
                     "cms_description": cms_description, "hospitals": hospitals,
                     "terms": search_terms(code, f"{description} {cms_description or ''}", rules)})
            for key, code, code_type, description, shoppable, cms_description, hospitals in rows]  # fmt: skip
