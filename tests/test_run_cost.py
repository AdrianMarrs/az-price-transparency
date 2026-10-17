from datetime import date
from decimal import Decimal

import pytest

from scripts.run_cost import ECS, record, run_days


class FakeTable:
    def __init__(self, items):
        self.items = list(items)

    def query(self, KeyConditionExpression, ExpressionAttributeValues):
        pk = ExpressionAttributeValues[":pk"]
        return {"Items": [i for i in self.items if i["PK"] == pk]}

    def put_item(self, Item):
        self.items.append(Item)


class FakeCostExplorer:
    def __init__(self, daily):
        self.daily, self.calls = daily, []

    def get_cost_and_usage(self, **kwargs):
        self.calls.append(kwargs)
        return {"ResultsByTime": [
            {"TimePeriod": {"Start": day}, "Total": {"UnblendedCost": {"Amount": amount}},
             "Estimated": estimated}
            for day, (amount, estimated) in self.daily.items()]}  # fmt: skip


def summary(started, finished, hours, estimate):
    return {"PK": "RUN#cigna#2026-10", "SK": f"SUMMARY#{started}", "started_at": started,
            "finished_at": finished, "hours": Decimal(hours), "estimated_cost_usd": Decimal(estimate)}  # fmt: skip


def test_run_days_cover_a_run_past_midnight():
    runs = [summary("2026-11-05T23:30:00+00:00", "2026-11-06T00:40:00+00:00", "1.1", "0.17")]
    assert run_days(runs) == [date(2026, 11, 5), date(2026, 11, 6)]


def test_record_sums_ecs_cost_on_the_run_days():
    table = FakeTable([
        summary("2026-10-17T19:13:42+00:00", "2026-10-17T20:14:49+00:00", "1.018", "0.1609"),
        summary("2026-10-17T20:21:00+00:00", "2026-10-17T20:24:15+00:00", "0.054", "0.0085"),
        {"PK": "RUN#cigna#2026-10", "SK": "FILE#x", "status": "done"},
    ])  # fmt: skip
    ce = FakeCostExplorer({"2026-10-17": ("0.1702", True), "2026-10-18": ("0.5", False)})
    cost = record("cigna", "2026-10", table, ce)
    assert cost["days"] == ["2026-10-17"] and cost["runs"] == 2
    assert cost["actual_usd"] == Decimal("0.1702") and cost["actual_is_preliminary"] is True
    assert cost["estimated_usd"] == Decimal("0.1694")
    assert ce.calls[0]["Filter"] == {"Dimensions": {"Key": "SERVICE", "Values": [ECS]}}
    assert ce.calls[0]["TimePeriod"] == {"Start": "2026-10-17", "End": "2026-10-18"}
    assert table.items[-1]["SK"] == "COST"


def test_no_runs_is_an_error():
    with pytest.raises(SystemExit):
        record("cigna", "2026-09", FakeTable([]), FakeCostExplorer({}))
