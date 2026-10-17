"""Record what a month's insurer runs actually cost, from AWS Cost Explorer.

Usage:
    uv run python scripts/run_cost.py [--insurer cigna] --month 2026-10

Reads the month's SUMMARY#<start> items from the runs table (RUNS_TABLE), asks Cost
Explorer for the ECS (Fargate) charge on the days they ran, and writes a COST item next to
them: actual and estimated dollars. Cost Explorer is daily here, and ECS runs nothing else in
this account, so a day's ECS charge is that day's runs. Its figures lag by up to a day and
are marked estimated until AWS finalizes them; rerun later for the final number. Each Cost
Explorer request costs $0.01.
"""

import argparse
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import boto3

ECS = "Amazon Elastic Container Service"


def run_days(summaries: list[dict]) -> list[date]:
    """Every UTC day any of the runs was running on."""
    days = set()
    for s in summaries:
        day = datetime.fromisoformat(s["started_at"]).date()
        end = datetime.fromisoformat(s["finished_at"]).date()
        while day <= end:
            days.add(day)
            day += timedelta(days=1)
    return sorted(days)


def ecs_cost(days: list[date], ce=None) -> tuple[Decimal, bool]:
    """(ECS dollars over those days, whether any figure is still an estimate)."""
    ce = ce or boto3.client("ce", region_name="us-east-1")  # Cost Explorer's one endpoint
    result = ce.get_cost_and_usage(
        TimePeriod={
            "Start": days[0].isoformat(),
            "End": (days[-1] + timedelta(days=1)).isoformat(),
        },
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        Filter={"Dimensions": {"Key": "SERVICE", "Values": [ECS]}},
    )
    wanted = {d.isoformat() for d in days}
    total, estimated = Decimal(0), False
    for r in result["ResultsByTime"]:
        if r["TimePeriod"]["Start"] in wanted:
            total += Decimal(r["Total"]["UnblendedCost"]["Amount"])
            estimated |= r.get("Estimated", False)
    return total, estimated


def record(insurer: str, month: str, table, ce=None) -> dict:
    pk = f"RUN#{insurer}#{month}"
    items = table.query(KeyConditionExpression="PK = :pk",
                        ExpressionAttributeValues={":pk": pk})["Items"]  # fmt: skip
    summaries = [i for i in items if i["SK"].startswith("SUMMARY#")]
    if not summaries:
        raise SystemExit(f"no runs recorded for {pk}")
    days = run_days(summaries)
    actual, estimated = ecs_cost(days, ce)
    cost = {
        "PK": pk, "SK": "COST", "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "days": [d.isoformat() for d in days], "runs": len(summaries),
        "hours": sum(Decimal(str(s["hours"])) for s in summaries),
        "estimated_usd": sum(Decimal(str(s.get("estimated_cost_usd") or 0)) for s in summaries),
        "actual_usd": actual, "actual_is_preliminary": estimated,
    }  # fmt: skip
    table.put_item(Item=cost)
    return cost


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--insurer", default="cigna")
    parser.add_argument("--month", required=True)
    args = parser.parse_args()
    table = boto3.resource("dynamodb").Table(
        os.environ.get("RUNS_TABLE", "az-price-transparency-runs")
    )
    cost = record(args.insurer, args.month, table)
    print({k: v for k, v in cost.items() if k not in ("PK", "SK")})


if __name__ == "__main__":
    main()
