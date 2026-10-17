"""DynamoDB export tests: a fake table, and a real Postgres schema (skipped if it's down)."""

import json
from decimal import Decimal

import psycopg
import pytest

from serving.export_dynamodb import DATABASE_URL, ItemTooLarge, compact, export, to_item

SCHEMA = "test_export"
STATE = f"{SCHEMA}.export_state"


class FakeBatch:
    def __init__(self, table):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def put_item(self, Item):
        self.table.items[(Item["PK"], Item["SK"])] = Item
        self.table.puts += 1

    def delete_item(self, Key):
        del self.table.items[(Key["PK"], Key["SK"])]


class FakeTable:
    def __init__(self):
        self.items, self.puts = {}, 0

    def batch_writer(self, **kwargs):
        return FakeBatch(self)


def service_row(ccn: str, code: str, amount: float) -> tuple:
    item = json.dumps({"ccn": ccn, "service_key": code, "description": None,
                       "prices": [{"payer": "Aetna", "amount": amount}]})  # fmt: skip
    pk, sk = f"HOSPITAL#{ccn}", f"SERVICE#{code}"
    return (f"{pk}|{sk}", pk, sk, sk, pk, item, str(hash(item)))


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running")
    with connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        connection.execute(f"CREATE SCHEMA {SCHEMA}")
        connection.execute(f"""CREATE TABLE {SCHEMA}.srv_hospital_service_items (
            item_key text, pk text, sk text, gsi1pk text, gsi1sk text, item text,
            content_hash text)""")
        connection.execute(f"""CREATE TABLE {SCHEMA}.srv_hospital_profiles (
            item_key text, pk text, sk text, item text, content_hash text)""")
        yield connection
        connection.execute(f"DROP SCHEMA {SCHEMA} CASCADE")


def set_items(conn, rows):
    conn.execute(f"TRUNCATE {SCHEMA}.srv_hospital_service_items")
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {SCHEMA}.srv_hospital_service_items VALUES (%s,%s,%s,%s,%s,%s,%s)", rows
        )


def run(conn, table, **kwargs):
    return export(table, conn, source=SCHEMA, state=STATE, **kwargs)


def test_to_item_keys_decimals_and_no_nulls():
    item = to_item("HOSPITAL#030006", "SERVICE#x", "SERVICE#x", "HOSPITAL#030006",
                   '{"a": 1.25, "b": null, "c": [{"d": null, "e": 2}]}')  # fmt: skip
    assert item == {"PK": "HOSPITAL#030006", "SK": "SERVICE#x", "GSI1PK": "SERVICE#x",
                    "GSI1SK": "HOSPITAL#030006", "a": Decimal("1.25"), "c": [{"e": 2}]}  # fmt: skip


def test_profiles_get_no_index_keys():
    assert set(to_item("HOSPITAL#1", "PROFILE", None, None, "{}")) == {"PK", "SK"}


def test_items_over_the_limit_fail_loudly():
    with pytest.raises(ItemTooLarge):
        to_item("HOSPITAL#1", "SERVICE#x", None, None, json.dumps({"x": "a" * 400_000}))


def test_compact_keeps_falsy_values():
    assert compact({"a": 0, "b": False, "c": "", "d": None}) == {"a": 0, "b": False, "c": ""}


def test_export_writes_only_changes_and_deletes_removed_items(conn):
    table = FakeTable()
    set_items(conn, [service_row("030006", "A", 1.0), service_row("030006", "B", 2.0)])
    assert run(conn, table)["put"] == 2

    assert run(conn, table) == {"put": 0, "deleted": 0, "bytes": 0}  # same input: no writes
    assert table.puts == 2

    set_items(conn, [service_row("030006", "A", 1.5)])  # A changed, B gone
    counts = run(conn, table)
    assert (counts["put"], counts["deleted"]) == (1, 1)
    assert list(table.items) == [("HOSPITAL#030006", "SERVICE#A")]
    assert table.items[("HOSPITAL#030006", "SERVICE#A")]["prices"][0]["amount"] == Decimal("1.5")


def test_dry_run_writes_nothing(conn):
    table = FakeTable()
    set_items(conn, [service_row("030006", "A", 1.0)])
    assert run(conn, table, dry_run=True)["put"] == 1
    assert table.puts == 0
    assert run(conn, table)["put"] == 1  # nothing was recorded as exported
