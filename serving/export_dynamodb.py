"""Export the serving items from Postgres to DynamoDB, writing only what changed.

Usage:
    uv run python -m serving.export_dynamodb [--dry-run]

Reads the items dbt builds (serving.srv_hospital_service_items and
serving.srv_hospital_profiles), compares each item's content_hash with what the last export
wrote (raw.dynamodb_export_state), puts the new and changed items and deletes the ones no
longer produced. The state is updated chunk by chunk, only after DynamoDB has accepted the
chunk, so an interrupted export resumes where it stopped and a rerun with the same input
writes nothing. Key design and costs: docs/03-cloud.md.

Needs PRICES_TABLE (the table name; terraform -chdir=infra/main output prices_table) and
AWS credentials (AWS_PROFILE locally).
"""

import argparse
import json
import os
import sys
import time
from decimal import Decimal

import boto3
import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://pt:pt@localhost:5432/prices")
MAX_ITEM_BYTES = 350_000  # DynamoDB's limit is 400 KB; dbt tests the same bound
CHUNK = 500

STATE_SQL = """
CREATE TABLE IF NOT EXISTS {state} (
    item_key     text PRIMARY KEY,
    pk           text NOT NULL,
    sk           text NOT NULL,
    content_hash text NOT NULL,
    exported_at  timestamptz NOT NULL DEFAULT now()
)
"""

SOURCE_SQL = """
SELECT item_key, pk, sk, gsi1pk, gsi1sk, item, content_hash
FROM {source}.srv_hospital_service_items
UNION ALL
SELECT item_key, pk, sk, NULL, NULL, item, content_hash
FROM {source}.srv_hospital_profiles
"""


class ItemTooLarge(Exception):
    """An item over MAX_ITEM_BYTES: fail loudly rather than truncate it."""


def compact(value):
    """Drop null attributes (they cost bytes and DynamoDB doesn't need them)."""
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def to_item(pk: str, sk: str, gsi1pk: str | None, gsi1sk: str | None, item: str) -> dict:
    """One DynamoDB item from a dbt row. Numbers become Decimal, as boto3 requires."""
    if len(item.encode()) > MAX_ITEM_BYTES:
        raise ItemTooLarge(f"{pk} {sk}: {len(item.encode()):,} bytes")
    keys = {"PK": pk, "SK": sk}
    if gsi1pk:  # profiles have no index keys, so they stay out of by_service
        keys |= {"GSI1PK": gsi1pk, "GSI1SK": gsi1sk}
    return keys | compact(json.loads(item, parse_float=Decimal))


def changed_rows(conn: psycopg.Connection, source: str, state: str):
    """New or changed items, streamed with a server-side cursor."""
    sql = f"""
        SELECT s.item_key, s.pk, s.sk, s.gsi1pk, s.gsi1sk, s.item, s.content_hash
        FROM ({SOURCE_SQL.format(source=source)}) AS s
        LEFT JOIN {state} AS e USING (item_key)
        WHERE e.content_hash IS DISTINCT FROM s.content_hash
        ORDER BY s.item_key"""
    with conn.transaction(), conn.cursor(name="changed_items") as cur:
        cur.itersize = CHUNK
        cur.execute(sql)
        yield from cur


def removed_rows(conn: psycopg.Connection, source: str, state: str) -> list[tuple]:
    """Items exported before that dbt no longer produces."""
    return conn.execute(f"""
        SELECT e.item_key, e.pk, e.sk FROM {state} AS e
        WHERE NOT EXISTS (
            SELECT 1 FROM ({SOURCE_SQL.format(source=source)}) AS s
            WHERE s.item_key = e.item_key)""").fetchall()


def chunks(rows, size: int = CHUNK):
    chunk = []
    for row in rows:
        chunk.append(row)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def export(table, conn: psycopg.Connection, source: str = "serving",
           state: str = "raw.dynamodb_export_state", dry_run: bool = False) -> dict:  # fmt: skip
    """Put changed items and delete removed ones; returns counts."""
    conn.execute(STATE_SQL.format(state=state))
    counts = {"put": 0, "deleted": 0, "bytes": 0}
    # A second connection writes the state while the first streams the changed rows.
    with psycopg.connect(conn.info.dsn, password=conn.info.password, autocommit=True) as writer:
        for chunk in chunks(changed_rows(conn, source, state)):
            items = [to_item(r[1], r[2], r[3], r[4], r[5]) for r in chunk]
            counts["bytes"] += sum(len(r[5].encode()) for r in chunk)
            if not dry_run:
                with table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
                    for item in items:
                        batch.put_item(Item=item)
                # Only now, with DynamoDB holding the chunk, record it as exported.
                writer.cursor().executemany(
                    f"""INSERT INTO {state} (item_key, pk, sk, content_hash) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (item_key) DO UPDATE
                        SET content_hash = EXCLUDED.content_hash, exported_at = now()""",
                    [(r[0], r[1], r[2], r[6]) for r in chunk],
                )
            counts["put"] += len(chunk)

    for chunk in chunks(removed_rows(conn, source, state)):
        if not dry_run:
            with table.batch_writer() as batch:
                for _, pk, sk in chunk:
                    batch.delete_item(Key={"PK": pk, "SK": sk})
            conn.execute(f"DELETE FROM {state} WHERE item_key = ANY(%s)", ([r[0] for r in chunk],))
        counts["deleted"] += len(chunk)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="count what would change")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    table_name = os.environ.get("PRICES_TABLE")
    if not table_name and not args.dry_run:
        raise SystemExit("set PRICES_TABLE (terraform -chdir=infra/main output prices_table)")
    table = boto3.resource("dynamodb").Table(table_name) if table_name else None
    started = time.perf_counter()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        counts = export(table, conn, dry_run=args.dry_run)
    seconds = time.perf_counter() - started
    verb = "would put" if args.dry_run else "put"
    print(f"{verb} {counts['put']:,} items ({counts['bytes'] / 1e6:,.0f} MB), "
          f"deleted {counts['deleted']:,}, in {seconds:,.0f}s")  # fmt: skip


if __name__ == "__main__":
    main()
