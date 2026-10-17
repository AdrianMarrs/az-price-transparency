"""The Dagster code location loads and is wired the way the pipeline expects.

Needs warehouse/target/manifest.json (`dbt parse`), which CI runs before the tests.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg

from orchestration.definitions import defs, hospital_partitions, in_scope_hospitals

GRAPH = defs.resolve_asset_graph()


def parents(key: dg.AssetKey) -> set[dg.AssetKey]:
    return set(GRAPH.get(key).parent_keys)


def test_definitions_load():
    dg.Definitions.validate_loadable(defs)


def test_one_partition_per_in_scope_hospital():
    assert hospital_partitions.get_partition_keys() == sorted(in_scope_hospitals()["ccn"])
    assert len(hospital_partitions.get_partition_keys()) == 95


def test_dbt_sources_are_fed_by_the_python_assets():
    # dbt's source('raw', 'hospital_charges') must resolve to the Python loader's asset,
    # or Dagster would build dbt models without waiting for new prices.
    stg = next(k for k in GRAPH.get_all_asset_keys() if k.path[-1] == "stg_hospital_charges")
    assert dg.AssetKey(["raw", "hospital_charges"]) in parents(stg)
    payer_plans = next(k for k in GRAPH.get_all_asset_keys() if k.path[-1] == "dim_payer_plans")
    assert dg.AssetKey(["raw", "payer_plans"]) in parents(payer_plans)


def test_hospital_assets_chain_in_order():
    assert parents(dg.AssetKey("price_file")) == {dg.AssetKey("hospital_sources")}
    assert parents(dg.AssetKey("parsed_prices")) == {dg.AssetKey("price_file")}
    assert parents(dg.AssetKey(["raw", "hospital_charges"])) == {dg.AssetKey("parsed_prices")}


def test_weekly_schedule_requests_one_run_per_hospital():
    schedule = defs.get_schedule_def("weekly_hospital_refresh")
    tick = datetime(2026, 10, 19, 7, tzinfo=ZoneInfo("America/Phoenix"))
    context = dg.build_schedule_context(
        scheduled_execution_time=tick, repository_def=defs.get_repository_def()
    )
    requests = schedule.evaluate_tick(context)
    keys = [r.partition_key for r in requests.run_requests]
    assert sorted(keys) == hospital_partitions.get_partition_keys()
    assert len({r.run_key for r in requests.run_requests}) == 95


def test_dynamodb_export_follows_the_serving_models():
    assert parents(dg.AssetKey("dynamodb_items")) == {
        dg.AssetKey("srv_hospital_service_items"),
        dg.AssetKey("srv_hospital_profiles"),
    }
