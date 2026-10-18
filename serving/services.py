"""The service list: every service at least one hospital prices, with plain-English search
terms, as the site searches it (data/<state>/search.json, written by export_static.py).
"""

import csv
import re
from pathlib import Path

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


def services_list(conn, state: str | None = None) -> list[dict]:
    """Every service at least one hospital prices, for search (data/<state>/search.json);
    with a state, only that state's hospitals are counted."""
    rules = load_search_terms()
    if state is None:
        rows = conn.execute("""
            SELECT service_key, code, code_type, common_description, cms_shoppable_id,
                   cms_description, hospitals
            FROM marts.dim_services WHERE hospitals > 0 ORDER BY service_key""").fetchall()
    else:
        rows = conn.execute(
            """
            SELECT s.service_key, s.code, s.code_type, s.common_description,
                   s.cms_shoppable_id, s.cms_description, n.hospitals
            FROM marts.dim_services AS s
            JOIN (SELECT service_key, count(DISTINCT ccn) AS hospitals
                  FROM serving.srv_service_prices WHERE lower(state) = ?
                  GROUP BY service_key) AS n USING (service_key)
            ORDER BY s.service_key""",
            [state.lower()],
        ).fetchall()
    return [compact({"id": service_id(key), "key": key, "code": code, "code_type": code_type,
                     "description": description, "cms_shoppable_id": shoppable,
                     "cms_description": cms_description, "hospitals": hospitals,
                     "terms": search_terms(code, f"{description} {cms_description or ''}", rules)})
            for key, code, code_type, description, shoppable, cms_description, hospitals in rows]  # fmt: skip
