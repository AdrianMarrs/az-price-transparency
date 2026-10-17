"""Insurer loader tests against a real Postgres. Skipped if Postgres is down."""

import polars as pl
import psycopg
import pytest

from ingest.hospitals.load import DATABASE_URL
from ingest.insurers.load import create_table, load_network
from ingest.insurers.normalize import SCHEMA as COLUMNS

SCHEMA = "test_insurer_load"


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


def frame(network: str, n: int, month: str = "2026-10") -> pl.DataFrame:
    rows = [
        {"insurer": "cigna", "network": network, "month": month, "ccn": "030006",
         "billing_code_type": "CPT", "billing_code": "73721", "description": "MRI knee",
         "negotiation_arrangement": "ffs", "negotiated_type": "negotiated",
         "negotiated_rate": 100.0 + i, "billing_class": "institutional", "setting": "outpatient",
         "service_codes": "11,22" if i else None, "modifiers": None, "expiration_date": "9999-12-31"}
        for i in range(n)
    ]  # fmt: skip
    return pl.DataFrame(rows, schema=COLUMNS)


def counts(conn) -> dict:
    return dict(
        conn.execute(
            f"SELECT network || '/' || month, count(*) FROM {SCHEMA}.insurer_rates GROUP BY 1"
        ).fetchall()
    )


def test_copy_round_trips_values_and_nulls(conn):
    assert load_network(conn, frame("arizona-hmo", 2), SCHEMA) == 2
    rows = conn.execute(
        f"SELECT negotiated_rate, service_codes FROM {SCHEMA}.insurer_rates ORDER BY 1"
    ).fetchall()
    assert rows == [(100.0, None), (101.0, "11,22")]


def test_reloading_a_network_replaces_only_its_rows(conn):
    load_network(conn, frame("arizona-hmo", 5), SCHEMA)
    load_network(conn, frame("phoenix-az-connect", 2), SCHEMA)
    load_network(conn, frame("arizona-hmo", 4, month="2026-11"), SCHEMA)
    load_network(conn, frame("arizona-hmo", 3), SCHEMA)
    assert counts(conn) == {
        "arizona-hmo/2026-10": 3,
        "arizona-hmo/2026-11": 4,
        "phoenix-az-connect/2026-10": 2,
    }


def test_a_frame_must_be_one_network(conn):
    mixed = pl.concat([frame("arizona-hmo", 1), frame("phoenix-az-connect", 1)])
    with pytest.raises(ValueError):
        load_network(conn, mixed, SCHEMA)


def test_an_empty_frame_loads_nothing(conn):
    assert load_network(conn, pl.DataFrame(schema=COLUMNS), SCHEMA) == 0
