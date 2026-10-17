"""The price lookup API: an AWS Lambda handler behind an API Gateway HTTP API.

    GET /services?q=knee mri              search services (from services.json, not DynamoDB)
    GET /services/{id}/prices?payer=aetna  every hospital's prices for one service
    GET /providers/{ccn}                   one hospital: compliance score, shoppable prices

{id} is a service id from search, e.g. cpt-hcpcs:73721 or ms-drg:470. payer filters by
payer, plan or parent company name; market (commercial, medicaid, ...) by market.

A plain handler rather than a web framework: boto3 is already in the Lambda runtime, so the
deployment package is this one file. Prices are published standard charges, not quotes.
Key design: docs/03-cloud.md.
"""

import base64
import gzip
import json
import os
import re
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ.get("PRICES_TABLE", "az-price-transparency-prices")
DATA_BUCKET = os.environ.get("DATA_BUCKET", "")
SERVICES_KEY = os.environ.get("SERVICES_KEY", "serving/services.json")
SEARCH_LIMIT = 25
NOTE = "Published hospital standard charges, not a quote. Check with your insurer and hospital."
# CloudFront keeps an answer a day (s-maxage) and is cleared after each weekly export;
# browsers keep it five minutes (max-age), so a cleared cache reaches people quickly.
CACHE_CONTROL = "public, max-age=300, s-maxage=86400"

_table = None
_services = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE)
    return _table


def services() -> list[dict]:
    """The service list, loaded once per Lambda instance (cold start)."""
    global _services
    if _services is None:
        body = boto3.client("s3").get_object(Bucket=DATA_BUCKET, Key=SERVICES_KEY)["Body"]
        _services = json.loads(body.read())
    return _services


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


def search(q: str) -> list[dict]:
    """Services whose code or description contains every word of q. CMS shoppable services
    first, then by how many hospitals price them."""
    words = q.lower().split()
    if not words:
        raise BadRequest("q is required, e.g. /services?q=knee mri")
    hits = []
    for s in services():
        fields = ("code", "description", "cms_description", "terms")  # terms: plain-English
        text = " ".join(str(s.get(k, "")) for k in fields)
        if all(w in text.lower() for w in words):
            hits.append(s)
    hits.sort(key=lambda s: ("cms_shoppable_id" not in s, -s.get("hospitals", 0), s["id"]))
    return hits[:SEARCH_LIMIT]


def service_by_id(service_id: str) -> dict:
    for s in services():
        if s["id"] == service_id.lower():
            return s
    raise NotFound(f"no service {service_id}")


def matches(price: dict, payer: str | None, market: str | None) -> bool:
    if market and price.get("market") != market.lower():
        return False
    if payer:
        names = " ".join(str(price.get(k, "")) for k in ("payer", "plan", "group")).lower()
        return payer.lower() in names
    return True


def profiles(ccns: list[str]) -> dict[str, dict]:
    """PROFILE items for these hospitals, by CCN (BatchGetItem takes 100 keys at a time)."""
    found, client = {}, table().meta.client
    for i in range(0, len(ccns), 100):
        keys = [{"PK": f"HOSPITAL#{c}", "SK": "PROFILE"} for c in ccns[i : i + 100]]
        request = {TABLE: {"Keys": keys, "ProjectionExpression":
                           "ccn, #n, city, county, score_pct, hospital_type",
                           "ExpressionAttributeNames": {"#n": "name"}}}  # fmt: skip
        while request:
            response = client.batch_get_item(RequestItems=request)
            for p in response["Responses"].get(TABLE, []):
                found[p["ccn"]] = p
            request = response.get("UnprocessedKeys") or None
    return found


def compare(service_id: str, payer: str | None, market: str | None) -> dict:
    """Every hospital's prices for one service, from the by_service index."""
    service = service_by_id(service_id)
    items, kwargs = [], {}
    while True:
        response = table().query(
            IndexName="by_service",
            KeyConditionExpression=Key("GSI1PK").eq(f"SERVICE#{service['key']}"),
            **kwargs,
        )
        items += response["Items"]
        if "LastEvaluatedKey" not in response:
            break
        kwargs = {"ExclusiveStartKey": response["LastEvaluatedKey"]}
    hospital = profiles([i["ccn"] for i in items])
    rows = []
    for i in items:
        prices = [p for p in i.get("prices", []) if matches(p, payer, market)]
        if (payer or market) and not prices:
            continue
        rows.append({"hospital": hospital.get(i["ccn"], {"ccn": i["ccn"]}),
                     "plans": i.get("plans", 0), "standard": i.get("standard", []),
                     "prices": prices})  # fmt: skip
    rows.sort(key=lambda r: r["hospital"].get("name", ""))
    return {"service": service, "filters": {"payer": payer, "market": market},
            "hospitals": rows, "note": NOTE}  # fmt: skip


def provider(ccn: str) -> dict:
    if not re.fullmatch(r"\d{6}", ccn):
        raise BadRequest("a CCN is six digits, e.g. /providers/030006")
    item = table().get_item(Key={"PK": f"HOSPITAL#{ccn}", "SK": "PROFILE"}).get("Item")
    if not item:
        raise NotFound(f"no hospital {ccn}")
    item = {k: v for k, v in item.items() if k not in ("PK", "SK")}
    return item | {"note": NOTE}


def route(method: str, path: str, query: dict) -> dict:
    if method != "GET":
        raise BadRequest("only GET is supported")
    if path == "/services":
        return {"services": search(query.get("q", ""))}
    if m := re.fullmatch(r"/services/([^/]+)/prices", path):
        return compare(m.group(1), query.get("payer"), query.get("market"))
    if m := re.fullmatch(r"/providers/([^/]+)", path):
        return provider(m.group(1))
    raise NotFound(f"no route {path}")


def to_json(value):
    """DynamoDB numbers arrive as Decimal; JSON wants int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"not JSON serializable: {type(value)}")


def respond(status: int, body: dict, gzip_ok: bool = False) -> dict:
    """The HTTP response. Compressed when the client accepts gzip: API Gateway HTTP APIs
    don't compress, and a compare response is several hundred KB of JSON."""
    text = json.dumps(body, default=to_json, separators=(",", ":"))
    headers = {"Content-Type": "application/json",
               "Cache-Control": CACHE_CONTROL if status == 200 else "no-store",
               "Vary": "Accept-Encoding"}  # fmt: skip
    if gzip_ok and len(text) > 1024:
        headers["Content-Encoding"] = "gzip"
        body64 = base64.b64encode(gzip.compress(text.encode(), compresslevel=5)).decode()
        return {"statusCode": status, "headers": headers, "body": body64, "isBase64Encoded": True}
    return {"statusCode": status, "headers": headers, "body": text}


def handler(event: dict, context=None) -> dict:
    """Entry point for an API Gateway HTTP API event (payload format 2.0)."""
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/").rstrip("/") or "/"
    gzip_ok = "gzip" in (event.get("headers") or {}).get("accept-encoding", "")
    try:
        result = route(method, path, event.get("queryStringParameters") or {})
        return respond(200, result, gzip_ok)
    except BadRequest as e:
        return respond(400, {"error": str(e)})
    except NotFound as e:
        return respond(404, {"error": str(e)})
