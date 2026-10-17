"""Dagster definitions: the hospital pipeline as assets, partitioned by hospital.

Run the UI:
    uv run dagster dev -m orchestration.definitions

Asset graph (left to right):
    hospital_list -> hospital_sources -> price_file[ccn] -> parsed_prices[ccn]
        -> raw/hospital_charges[ccn] -> dbt models
    parsed_prices -> raw/payer_plans, raw/compliance_checks -> dbt models
    dbt serving models -> dynamodb_items

price_file, parsed_prices and raw/hospital_charges have one partition per in-scope
hospital, so one hospital's bad file fails only its own partition.
"""

import json
import os
import urllib.request
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import boto3
import dagster as dg
import polars as pl
import psycopg
import redis
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

from ingest.hospitals import compliance, find_sources, hospital_list, payer_plans
from ingest.hospitals.download import download_hospitals
from ingest.hospitals.load import DATABASE_URL, create_table, load_parsed, state_of
from ingest.hospitals.parse import (
    PARSED_DIR,
    load_shoppable,
    newest_file,
    parse_one,
    update_report,
)
from serving import export_dynamodb

ROOT = Path(__file__).resolve().parents[1]
HOSPITALS_SEED = ROOT / "warehouse" / "seeds" / "hospitals.csv"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# Counties whose prices are loaded into Postgres ("*" = all; every hospital is parsed either
# way). Statewide adds several GB, so a small machine can set e.g. LOAD_COUNTIES=PIMA.
LOAD_COUNTIES = {c.strip().upper() for c in os.environ.get("LOAD_COUNTIES", "*").split(",")}
# Asset checks: flag a hospital whose parsed row count moves more than this between runs.
ROW_SWING = 0.30


def in_scope_hospitals() -> pl.DataFrame:
    return pl.read_csv(HOSPITALS_SEED, infer_schema_length=0).filter(
        pl.col("federally_run") == "false"
    )


hospital_partitions = dg.StaticPartitionsDefinition(sorted(in_scope_hospitals()["ccn"]))


@contextmanager
def hospital_lock(ccn: str, run_id: str):
    """Redis lock so two runs never download the same hospital's file at once."""
    client = redis.Redis.from_url(REDIS_URL)
    key = f"lock:price_file:{ccn}"
    if not client.set(key, run_id, nx=True, ex=3600):
        raise dg.Failure(f"{ccn} is already being downloaded by run {client.get(key)!r}")
    try:
        yield
    finally:
        if client.get(key) == run_id.encode():
            client.delete(key)


# ---------- discovery (weekly, not partitioned) ----------


@dg.asset(group_name="discovery", description="In-scope hospitals from CMS's general info file")
def hospital_list_seed(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    hospitals, modified = hospital_list.refresh_hospital_list("AZ")
    federal = hospitals.filter(pl.col("federally_run")).height
    return dg.MaterializeResult(
        metadata={
            "hospitals": hospitals.height,
            "federally_run": federal,
            "cms_file_modified": modified,
        }
    )


@dg.asset(group_name="discovery", deps=[hospital_list_seed],
          description="Each hospital's price file, found through its cms-hpt.txt")  # fmt: skip
def hospital_sources() -> dg.MaterializeResult:
    find_sources.main()
    sources = pl.read_csv(find_sources.OUTPUT_PATH, infer_schema_length=0)
    counts = dict(sources["status"].value_counts().rows())
    return dg.MaterializeResult(metadata={"statuses": dg.MetadataValue.json(counts)})


# ---------- per hospital (partitioned) ----------


@dg.asset(group_name="hospitals", partitions_def=hospital_partitions, deps=[hospital_sources])
def price_file(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """Download the hospital's price file (or confirm it is unchanged)."""
    ccn = context.partition_key
    with hospital_lock(ccn, context.run_id):
        rows = download_hospitals([ccn])
    if not rows:
        return dg.MaterializeResult(metadata={"outcome": "no price file URL"})
    row = rows[0]
    return dg.MaterializeResult(
        metadata={
            "outcome": row["outcome"],
            "size_mb": round((row.get("size_bytes") or 0) / 1e6),
            "detail": row.get("error") or row.get("path") or "",
        }
    )


@dg.asset(group_name="hospitals", partitions_def=hospital_partitions, deps=[price_file])
def parsed_prices(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """Parse the newest file into data/parsed/<ccn>.parquet and update the parse report."""
    ccn = context.partition_key
    path = newest_file(ccn)
    if path is None:
        return dg.MaterializeResult(metadata={"outcome": "no file"})
    entry = parse_one(ccn, path, load_shoppable())
    update_report([entry])
    if entry["outcome"] == "failed":
        raise dg.Failure(f"{ccn}: {entry['error']}")
    return dg.MaterializeResult(
        metadata={
            "outcome": entry["outcome"],
            "valid": int(entry.get("valid") or 0),
            "rejected": int(entry.get("rejected") or 0),
            "last_updated_on": str(entry.get("last_updated_on") or ""),
        }
    )


@dg.asset_check(asset=parsed_prices, description="Row count moved more than 30% since last run")
def parsed_row_count_stable(context: dg.AssetCheckExecutionContext) -> dg.AssetCheckResult:
    events = context.instance.fetch_materializations(parsed_prices.key, limit=50).records
    ccn = context.partition_key if context.has_partition_key else None
    counts = [
        e.asset_materialization.metadata["valid"].value
        for e in events
        if e.asset_materialization and e.asset_materialization.partition == ccn
        and "valid" in e.asset_materialization.metadata
    ][:2]  # fmt: skip
    if len(counts) < 2 or counts[1] == 0:
        return dg.AssetCheckResult(passed=True, metadata={"note": "no earlier run to compare"})
    swing = abs(counts[0] - counts[1]) / counts[1]
    return dg.AssetCheckResult(
        passed=swing <= ROW_SWING, severity=dg.AssetCheckSeverity.WARN,
        metadata={"previous": counts[1], "current": counts[0], "swing": f"{swing:.0%}"},
    )  # fmt: skip


@dg.asset_check(asset=parsed_prices, description="File's last_updated_on is within a year")
def parsed_file_is_current(context: dg.AssetCheckExecutionContext) -> dg.AssetCheckResult:
    report = pl.read_csv(PARSED_DIR / "parse_report.csv", infer_schema_length=0)
    ccn = context.partition_key if context.has_partition_key else None
    row = report.filter(pl.col("ccn") == ccn).to_dicts()
    updated = (row[0].get("last_updated_on") or "") if row else ""
    current = bool(updated) and date.fromisoformat(updated) >= date.today() - timedelta(days=365)
    return dg.AssetCheckResult(passed=current, severity=dg.AssetCheckSeverity.WARN,
                               metadata={"last_updated_on": updated or "missing"})  # fmt: skip


@dg.asset(
    key=["raw", "hospital_charges"],
    group_name="hospitals",
    partitions_def=hospital_partitions,
    deps=[parsed_prices],
    description="Prices loaded into Postgres (counties in LOAD_COUNTIES; default all)",
)
def warehouse_prices(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    ccn = context.partition_key
    county = in_scope_hospitals().filter(pl.col("ccn") == ccn)["county"].item().upper()
    wanted = "*" in LOAD_COUNTIES or county in LOAD_COUNTIES
    if not wanted or not (PARSED_DIR / f"{ccn}.parquet").exists():
        return dg.MaterializeResult(metadata={"loaded": False, "county": county})
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        create_table(conn)
        df = load_parsed(conn, ccn, state_of(ccn))
    return dg.MaterializeResult(metadata={"loaded": True, "rows": df.height})


# ---------- statewide tables read by dbt ----------


@dg.asset(key=["raw", "payer_plans"], group_name="statewide", deps=[parsed_prices])
def payer_plan_names() -> None:
    """Every payer and plan name in the parsed files (for dim_payer_plans)."""
    payer_plans.main()


@dg.asset(key=["raw", "compliance_checks"], group_name="statewide",
          deps=[hospital_sources, parsed_prices])  # fmt: skip
def compliance_checks() -> dg.MaterializeResult:
    compliance.main()
    with psycopg.connect(DATABASE_URL) as conn:
        passed, failed = conn.execute(
            "SELECT count(*) FILTER (WHERE passed), count(*) FILTER (WHERE NOT passed) "
            "FROM raw.compliance_checks"
        ).fetchone()
    return dg.MaterializeResult(metadata={"passed": passed, "failed": failed})


# ---------- dbt ----------

dbt_project = DbtProject(project_dir=ROOT / "warehouse", profiles_dir=ROOT / "warehouse")
dbt_project.prepare_if_dev()


@dbt_assets(manifest=dbt_project.manifest_path)
def warehouse_models(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


# ---------- serving ----------


@dg.asset(
    group_name="serving",
    deps=[dg.AssetKey("srv_hospital_service_items"), dg.AssetKey("srv_hospital_profiles")],
    description="Changed serving items written to DynamoDB (PRICES_TABLE); removed ones deleted",
)
def dynamodb_items(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    table_name = os.environ.get("PRICES_TABLE")
    if not table_name:
        raise dg.Failure(
            "PRICES_TABLE is not set (terraform -chdir=infra/main output prices_table)"
        )
    table = boto3.resource("dynamodb").Table(table_name)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        counts = export_dynamodb.export(table, conn)
        if bucket := os.environ.get("DATA_BUCKET"):  # the service list the API searches
            counts["services"] = export_dynamodb.export_services(conn, bucket)
    distribution = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID")
    if distribution and (counts["put"] or counts["deleted"]):  # new prices: clear the API cache
        counts["invalidation"] = export_dynamodb.invalidate_cache(distribution)
    context.log.info(f"put {counts['put']:,}, deleted {counts['deleted']:,}")
    return dg.MaterializeResult(metadata=counts | {"table": table_name})


# ---------- jobs, schedules, alerts ----------

discovery_job = dg.define_asset_job(
    "discovery", selection=dg.AssetSelection.assets(hospital_list_seed, hospital_sources)
)
hospital_job = dg.define_asset_job(
    "refresh_hospital",
    selection=dg.AssetSelection.assets(price_file, parsed_prices, warehouse_prices),
)
warehouse_job = dg.define_asset_job(
    "build_warehouse",
    selection=dg.AssetSelection.assets(payer_plan_names, compliance_checks)
    | dg.AssetSelection.assets(warehouse_models),
)
# Separate from build_warehouse so the warehouse builds without AWS (locally, in CI).
export_job = dg.define_asset_job(
    "export_serving", selection=dg.AssetSelection.assets(dynamodb_items)
)


@dg.schedule(job=discovery_job, cron_schedule="0 6 * * 1", execution_timezone="America/Phoenix")
def weekly_discovery():
    """Mondays 6:00: refresh the hospital list and find each price file."""
    return dg.RunRequest()


@dg.schedule(job=hospital_job, cron_schedule="0 7 * * 1", execution_timezone="America/Phoenix")
def weekly_hospital_refresh(context: dg.ScheduleEvaluationContext):
    """Mondays 7:00: one run per hospital, so a bad file fails only its own run."""
    for ccn in hospital_partitions.get_partition_keys():
        yield dg.RunRequest(run_key=f"{context.scheduled_execution_time:%Y-%m-%d}-{ccn}",
                            partition_key=ccn)  # fmt: skip


@dg.schedule(job=warehouse_job, cron_schedule="0 11 * * 1", execution_timezone="America/Phoenix")
def weekly_warehouse_build():
    """Mondays 11:00: payer names, compliance checks, then dbt build."""
    return dg.RunRequest()


@dg.schedule(job=export_job, cron_schedule="0 13 * * 1", execution_timezone="America/Phoenix")
def weekly_serving_export():
    """Mondays 13:00: write what changed to DynamoDB (the build takes about an hour)."""
    return dg.RunRequest()


@dg.run_failure_sensor(description="Post failed runs to ALERT_WEBHOOK_URL (Slack-compatible)")
def alert_on_failure(context: dg.RunFailureSensorContext):
    message = (f"az-price-transparency: run {context.dagster_run.job_name} failed: "
               f"{context.failure_event.message}")  # fmt: skip
    url = os.environ.get("ALERT_WEBHOOK_URL")
    if not url:
        context.log.warning(f"ALERT_WEBHOOK_URL not set; would have sent: {message}")
        return
    request = urllib.request.Request(
        url, data=json.dumps({"text": message}).encode(),
        headers={"Content-Type": "application/json"},
    )  # fmt: skip
    urllib.request.urlopen(request, timeout=10)


defs = dg.Definitions(
    assets=[hospital_list_seed, hospital_sources, price_file, parsed_prices, warehouse_prices,
            payer_plan_names, compliance_checks, warehouse_models, dynamodb_items],
    asset_checks=[parsed_row_count_stable, parsed_file_is_current],
    jobs=[discovery_job, hospital_job, warehouse_job, export_job],
    schedules=[weekly_discovery, weekly_hospital_refresh, weekly_warehouse_build,
               weekly_serving_export],
    sensors=[alert_on_failure],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)  # fmt: skip
