"""Streaming TiC parser tests on tiny hand-made files that follow the CMS schema."""

import gzip
import io
import json
import zipfile
import zlib

import httpx
import pytest

from ingest.insurers import tic
from ingest.insurers.tic import (
    FirstKey,
    arizona_groups,
    in_network_files,
    keep_rates,
    stream_file,
)

NPIS = {1111111111: "030006", 2222222222: "030011"}  # NPI -> CCN

REFS = [
    {"provider_group_id": 1, "provider_groups": [
        {"npi": [1111111111, 9999999999], "tin": {"type": "ein", "value": "1"}}]},
    {"provider_group_id": 2, "provider_groups": [
        {"npi": [8888888888], "tin": {"type": "ein", "value": "2"}}]},
    {"provider_group_id": 3, "provider_groups": [
        {"npi": [2222222222], "tin": {"type": "ein", "value": "3"}}]},
]  # fmt: skip
IN_NETWORK = [
    {"billing_code": "73721", "billing_code_type": "CPT", "negotiation_arrangement": "ffs",
     "negotiated_rates": [
         {"provider_references": [1, 2], "negotiated_prices": [
             {"negotiated_type": "negotiated", "negotiated_rate": 412.5, "setting": "outpatient"}]},
         {"provider_references": [2], "negotiated_prices": [
             {"negotiated_type": "negotiated", "negotiated_rate": 999.0}]},
     ]},
    {"billing_code": "99213", "billing_code_type": "CPT",
     "negotiated_rates": [{"provider_references": [2], "negotiated_prices": [
         {"negotiated_type": "negotiated", "negotiated_rate": 80.0}]}]},
    {"billing_code": "470", "billing_code_type": "MS-DRG",
     "negotiated_rates": [{"provider_references": [3, 1], "negotiated_prices": [
         {"negotiated_type": "negotiated", "negotiated_rate": 21000.0}]}]},
]  # fmt: skip


def gz(doc: dict) -> bytes:
    return gzip.compress(json.dumps(doc).encode())


def file_with(refs_first: bool) -> bytes:
    head = {"reporting_entity_name": "Test", "version": "1.0.0"}
    body = ({"provider_references": REFS, "in_network": IN_NETWORK} if refs_first
            else {"in_network": IN_NETWORK, "provider_references": REFS})  # fmt: skip
    return gz(head | body)


def test_arizona_groups_match_hospital_npis_only():
    assert arizona_groups(REFS[0], NPIS) == {"030006"}
    assert arizona_groups(REFS[1], NPIS) == set()


def test_keep_rates_drops_other_providers_and_tags_ccns():
    kept = keep_rates(IN_NETWORK[0], {1: {"030006"}})
    assert [r["ccns"] for r in kept["negotiated_rates"]] == [["030006"]]
    assert kept["negotiated_rates"][0]["provider_references"] == [1]
    assert keep_rates(IN_NETWORK[1], {1: {"030006"}}) is None


def test_keep_rates_matches_inline_provider_groups():
    item = {"billing_code": "73721", "negotiated_rates": [
        {"provider_groups": [{"npi": [2222222222], "tin": {"type": "ein", "value": "3"}}],
         "negotiated_prices": [{"negotiated_type": "negotiated", "negotiated_rate": 500.0}]},
        {"provider_groups": [{"npi": [8888888888], "tin": {"type": "ein", "value": "2"}}],
         "negotiated_prices": [{"negotiated_type": "negotiated", "negotiated_rate": 1.0}]},
        {"provider_references": [1], "negotiated_prices": [
            {"negotiated_type": "negotiated", "negotiated_rate": 400.0}]},
    ]}  # fmt: skip
    stats = {}
    kept = keep_rates(item, {1: {"030006"}}, NPIS, stats)
    assert [(r["ccns"], r["negotiated_prices"][0]["negotiated_rate"]) for r in kept["negotiated_rates"]] == [
        (["030011"], 500.0), (["030006"], 400.0)]  # fmt: skip
    assert "provider_groups" in kept["negotiated_rates"][0]
    assert stats["inline_group_rates"] == 2


def test_inline_groups_are_found_when_no_reference_is_kept(tmp_path):
    doc = {"reporting_entity_name": "Test", "provider_references": REFS[1:2], "in_network": [
        {"billing_code": "470", "billing_code_type": "MS-DRG", "negotiated_rates": [
            {"provider_groups": [{"npi": [1111111111], "tin": {"type": "ein", "value": "1"}}],
             "negotiated_prices": [{"negotiated_type": "negotiated", "negotiated_rate": 21000.0}]}]}]}  # fmt: skip
    path = tmp_path / "inline.json.gz"
    path.write_bytes(gz(doc))
    stats = {}
    items = list(stream_file(str(path), NPIS, stats=stats))
    assert stats["kept_groups"] == 0 and stats["inline_group_rates"] == 1
    assert items[0]["negotiated_rates"][0]["ccns"] == ["030006"]


@pytest.mark.parametrize("chunk", [7, 1 << 20])  # 7 bytes: chunk boundaries fall everywhere
def test_stream_file_keeps_arizona_rates(tmp_path, monkeypatch, chunk):
    monkeypatch.setattr(tic, "CHUNK", chunk)
    path = tmp_path / "rates.json.gz"
    path.write_bytes(file_with(refs_first=True))
    stats = {}
    items = list(stream_file(str(path), NPIS, stats=stats))
    assert [i["billing_code"] for i in items] == ["73721", "470"]
    assert items[1]["negotiated_rates"][0]["ccns"] == ["030006", "030011"]
    expected = {"refs_first": True, "references": 3, "kept_groups": 2, "codes": 3, "kept_codes": 2}
    assert {k: stats[k] for k in expected} == expected


@pytest.mark.parametrize("chunk", [7, 1 << 20])
def test_references_after_the_rates_are_still_found(tmp_path, monkeypatch, chunk):
    monkeypatch.setattr(tic, "CHUNK", chunk)
    path = tmp_path / "rates.json.gz"
    path.write_bytes(file_with(refs_first=False))
    stats = {}
    items = list(stream_file(str(path), NPIS, stats=stats))
    assert [i["billing_code"] for i in items] == ["73721", "470"]
    assert stats["refs_first"] is False


def serving(body: bytes, headers: dict | None = None) -> httpx.Client:
    """A client whose every request streams `body`, like a real download."""
    return httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, headers=headers, stream=httpx.ByteStream(body))))  # fmt: skip


def test_stream_file_reads_from_a_url():
    body = file_with(refs_first=True)
    stats = {}
    items = list(stream_file("https://example.org/rates.json.gz", NPIS, client=serving(body),
                             stats=stats))  # fmt: skip
    assert len(items) == 2 and stats["compressed"] >= len(body)  # two passes over a tiny file


def test_a_gzip_file_served_with_content_encoding_gzip_is_read_once_decompressed():
    # Cigna serves some .json.gz files with Content-Encoding: gzip; httpx must not undo it.
    client = serving(file_with(refs_first=True), {"Content-Encoding": "gzip"})
    items = list(stream_file("https://example.org/rates.json.gz", NPIS, client=client))
    assert [i["billing_code"] for i in items] == ["73721", "470"]


def zipped(data: bytes, method: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=method) as z:
        z.writestr("2026-10-01_partner_in-network-rates.json", data)
    return buffer.getvalue()


@pytest.mark.parametrize("method", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
@pytest.mark.parametrize("chunk", [7, 1 << 20])
def test_zip_and_plain_json_files_are_read_too(tmp_path, monkeypatch, method, chunk):
    monkeypatch.setattr(tic, "CHUNK", chunk)
    plain = gzip.decompress(file_with(refs_first=True))
    for name, body in [("rates.zip", zipped(plain, method)), ("rates.json", plain)]:
        (tmp_path / name).write_bytes(body)
        items = list(stream_file(str(tmp_path / name), NPIS))
        assert [i["billing_code"] for i in items] == ["73721", "470"], name


def test_several_gzip_members_are_one_file():
    doc = gzip.decompress(file_with(refs_first=True))
    two = gzip.compress(doc[:100]) + gzip.compress(doc[100:])
    assert b"".join(tic.decompress_chunks(iter([two]))) == doc


def test_a_cut_off_download_raises():
    body = file_with(refs_first=True)
    with pytest.raises(zlib.error):
        b"".join(tic.decompress_chunks(iter([body[: len(body) // 2]])))


def test_in_network_files_dedupes_and_filters_by_name():
    toc = {"reporting_structure": [
        {"in_network_files": [{"location": "https://x/a_arizona-hmo_in-network-rates.json.gz?sig=1"}]},
        {"in_network_files": [{"location": "https://x/a_arizona-hmo_in-network-rates.json.gz?sig=2"},
                              {"location": "https://x/b_texas_in-network-rates.json.gz"}]},
    ]}  # fmt: skip
    assert in_network_files(toc, "arizona-hmo") == [
        "https://x/a_arizona-hmo_in-network-rates.json.gz?sig=1"
    ]


def test_first_key_finds_a_needle_split_across_chunks():
    order = FirstKey(b'"provider_references"', b'"in_network"')
    assert order.feed(b'{"version":"1","in_net') is None
    assert order.feed(b'work":[{"provider_references":[1]}]}') == b'"in_network"'


@pytest.mark.parametrize("chunk", [7, 1 << 20])
def test_pass_one_stops_at_the_rates_when_references_come_first(tmp_path, monkeypatch, chunk):
    monkeypatch.setattr(tic, "CHUNK", chunk)
    monkeypatch.setattr(tic, "JSON_CHUNK", chunk)
    big = {"reporting_entity_name": "Test", "provider_references": REFS,
           "in_network": IN_NETWORK * 2000}  # fmt: skip
    path = tmp_path / "rates.json.gz"
    path.write_bytes(gz(big))
    stats = {}
    items = list(stream_file(str(path), NPIS, stats=stats))
    assert len(items) == 4000 and stats["refs_first"]
    if chunk == 7:  # pass 1 read only the beginning of the file
        assert stats["pass1_compressed"] < path.stat().st_size / 2
