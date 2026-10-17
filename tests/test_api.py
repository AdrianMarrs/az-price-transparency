import json
from decimal import Decimal

import pytest

from api import handler as api

SERVICES = [
    {"id": "cpt-hcpcs:73721", "key": "CPT/HCPCS:73721", "code": "73721",
     "description": "MRI knee without contrast", "cms_shoppable_id": 33, "hospitals": 56},
    {"id": "cpt-hcpcs:73722", "key": "CPT/HCPCS:73722", "code": "73722",
     "description": "MRI knee with contrast", "hospitals": 40},
    {"id": "ms-drg:470", "key": "MS-DRG:470", "code": "470",
     "description": "Major hip and knee joint replacement", "hospitals": 30},
]  # fmt: skip

PROFILE = {"PK": "HOSPITAL#030006", "SK": "PROFILE", "ccn": "030006",
           "name": "TUCSON MEDICAL CENTER", "city": "Tucson", "score_pct": Decimal(100)}  # fmt: skip
ITEM = {"PK": "HOSPITAL#030006", "SK": "SERVICE#CPT/HCPCS:73721", "ccn": "030006",
        "plans": Decimal(2), "standard": [{"type": "gross", "amount": Decimal("2500.5")}],
        "prices": [
            {"payer": "Aetna", "plan": "PPO", "group": "Aetna", "market": "commercial",
             "amount": Decimal("1421.79")},
            {"payer": "AHCCCS", "plan": "Banner UFC", "group": "AHCCCS", "market": "medicaid",
             "amount": Decimal(167)},
        ]}  # fmt: skip


class FakeClient:
    def batch_get_item(self, RequestItems):
        keys = RequestItems[api.TABLE]["Keys"]
        hits = [PROFILE for k in keys if k["PK"] == PROFILE["PK"]]
        return {"Responses": {api.TABLE: hits}}


class FakeTable:
    class meta:
        client = FakeClient()

    def query(self, IndexName, KeyConditionExpression, **kwargs):
        assert IndexName == "by_service"
        key = KeyConditionExpression.get_expression()["values"][1]
        return {"Items": [ITEM] if key == "SERVICE#CPT/HCPCS:73721" else []}

    def get_item(self, Key):
        return {"Item": PROFILE} if Key == {"PK": PROFILE["PK"], "SK": "PROFILE"} else {}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(api, "_services", SERVICES)
    monkeypatch.setattr(api, "_table", FakeTable())


def get(path: str, **query) -> tuple[int, dict]:
    event = {"rawPath": path, "queryStringParameters": query or None,
             "requestContext": {"http": {"method": "GET"}}}  # fmt: skip
    response = api.handler(event)
    return response["statusCode"], json.loads(response["body"])


def test_search_puts_shoppable_services_first_and_needs_every_word():
    status, body = get("/services", q="MRI knee")
    assert status == 200
    assert [s["id"] for s in body["services"]] == ["cpt-hcpcs:73721", "cpt-hcpcs:73722"]
    assert get("/services", q="knee 470")[1]["services"][0]["id"] == "ms-drg:470"


def test_search_without_a_query_is_a_bad_request():
    assert get("/services")[0] == 400


def test_compare_joins_hospital_profiles_and_converts_decimals():
    status, body = get("/services/cpt-hcpcs:73721/prices")
    assert status == 200
    row = body["hospitals"][0]
    assert row["hospital"]["name"] == "TUCSON MEDICAL CENTER"
    assert row["plans"] == 2 and row["standard"][0]["amount"] == 2500.5
    assert len(row["prices"]) == 2
    assert "not a quote" in body["note"]


def test_compare_filters_by_payer_or_market():
    by_payer = get("/services/cpt-hcpcs:73721/prices", payer="aetna")[1]
    assert [p["amount"] for p in by_payer["hospitals"][0]["prices"]] == [1421.79]
    by_market = get("/services/cpt-hcpcs:73721/prices", market="medicaid")[1]
    assert [p["amount"] for p in by_market["hospitals"][0]["prices"]] == [167]
    assert get("/services/cpt-hcpcs:73721/prices", payer="cigna")[1]["hospitals"] == []


def test_unknown_service_or_hospital_is_404():
    assert get("/services/cpt-hcpcs:99999/prices")[0] == 404
    assert get("/providers/039999")[0] == 404
    assert get("/nowhere")[0] == 404


def test_provider_returns_the_profile_without_keys():
    status, body = get("/providers/030006")
    assert status == 200 and body["name"] == "TUCSON MEDICAL CENTER"
    assert "PK" not in body and body["score_pct"] == 100


def test_provider_rejects_a_malformed_ccn():
    assert get("/providers/abc")[0] == 400


def test_only_get_is_allowed():
    event = {"rawPath": "/services", "requestContext": {"http": {"method": "POST"}}}
    assert api.handler(event)["statusCode"] == 400
