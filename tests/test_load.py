"""Loader tests against a real Postgres (the local Docker one, or CI's service container).

Each test run uses its own schema and drops it afterwards. Skipped if Postgres is down.
"""

from decimal import Decimal

import polars as pl
import psycopg
import pytest

from ingest.hospitals.load import COLUMNS, DATABASE_URL, create_table, load_hospital

SCHEMA = "test_load"


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running")
    with connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        create_table(connection, SCHEMA)
        yield connection
        connection.execute(f"DROP SCHEMA {SCHEMA} CASCADE")


def frame(ccn: str, state: str, n: int) -> pl.DataFrame:
    rows = [
        {"state": state, "ccn": ccn, "source_file_id": 1, "description": f"MRI knee {i}",
         "code": "73721", "code_type": "CPT/HCPCS", "cms_shoppable_id": 33,
         "setting": "outpatient", "billing_class": "facility", "modifiers": None,
         "payer_name": "Aetna, Inc.", "plan_name": 'PPO "Choice"', "methodology": "case rate",
         "price_type": "negotiated_dollar", "amount": Decimal("689.1234"), "algorithm": None}
        for i in range(n)
    ]  # fmt: skip
    return pl.DataFrame(rows, schema_overrides={"amount": pl.Decimal(18, 4)}).select(COLUMNS)


def test_copy_round_trips_values_and_nulls(conn):
    load_hospital(conn, frame("030006", "AZ", 3), "030006", "AZ", SCHEMA)
    row = conn.execute(
        f"SELECT payer_name, plan_name, amount, modifiers, algorithm "
        f"FROM {SCHEMA}.hospital_charges LIMIT 1"
    ).fetchone()
    # commas and quotes survive CSV; nulls stay null, not empty strings
    assert row == ("Aetna, Inc.", 'PPO "Choice"', Decimal("689.1234"), None, None)


def test_reloading_a_hospital_replaces_its_rows(conn):
    load_hospital(conn, frame("030006", "AZ", 5), "030006", "AZ", SCHEMA)
    load_hospital(conn, frame("030064", "AZ", 2), "030064", "AZ", SCHEMA)
    load_hospital(conn, frame("030006", "AZ", 3), "030006", "AZ", SCHEMA)
    counts = dict(
        conn.execute(f"SELECT ccn, count(*) FROM {SCHEMA}.hospital_charges GROUP BY ccn").fetchall()
    )
    assert counts == {"030006": 3, "030064": 2}


def test_rows_land_in_their_state_partition_and_queries_prune(conn):
    load_hospital(conn, frame("030006", "AZ", 2), "030006", "AZ", SCHEMA)
    load_hospital(conn, frame("320001", "NM", 2), "320001", "NM", SCHEMA)
    per_partition = dict(
        conn.execute(
            f"SELECT tableoid::regclass::text, count(*) FROM {SCHEMA}.hospital_charges GROUP BY 1"
        ).fetchall()
    )
    assert per_partition == {f"{SCHEMA}.hospital_charges_az": 2,
                             f"{SCHEMA}.hospital_charges_nm": 2}  # fmt: skip
    plan = "\n".join(
        r[0]
        for r in conn.execute(
            f"EXPLAIN SELECT * FROM {SCHEMA}.hospital_charges WHERE state = 'AZ'"
        ).fetchall()
    )
    assert "hospital_charges_az" in plan and "hospital_charges_nm" not in plan


def test_bad_state_codes_are_refused(conn):
    with pytest.raises(ValueError, match="not a state code"):
        load_hospital(conn, frame("1", "az; DROP", 1), "1", "az; DROP", SCHEMA)
