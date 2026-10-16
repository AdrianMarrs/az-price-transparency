import gzip
import hashlib

import httpx

from ingest.hospitals.download import (
    LastDownload,
    conditional_headers,
    download,
    download_once,
    file_format,
)

URL = "https://example.org/files/123_example_standardcharges.csv"
BODY = b"description,code\nMRI knee,73721\n" * 1000


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_file_format_from_extension_then_content_type():
    assert file_format(URL, "text/plain") == "csv"
    assert file_format("https://x.org/a.JSON", "") == "json"
    assert file_format("https://x.org/download?id=1", "application/json") == "json"
    assert file_format("https://x.org/download", "text/html") == "unknown"


def test_conditional_headers():
    assert conditional_headers(None) == {}
    last = LastDownload("abc", "p", '"v1"', "Wed, 29 Apr 2026 00:00:00 GMT")
    assert conditional_headers(last) == {
        "If-None-Match": '"v1"',
        "If-Modified-Since": "Wed, 29 Apr 2026 00:00:00 GMT",
    }


def test_download_writes_gzip_and_hashes_original_bytes(tmp_path):
    client = client_for(lambda r: httpx.Response(200, content=BODY, headers={"etag": '"v1"'}))
    row = download_once(client, "030006", URL, tmp_path, None)
    assert row["outcome"] == "downloaded"
    assert row["sha256"] == hashlib.sha256(BODY).hexdigest()
    assert row["size_bytes"] == len(BODY)
    assert row["etag"] == '"v1"'
    path = tmp_path / "030006_123_example_standardcharges.csv.gz"
    assert row["path"] == path.as_posix()
    assert gzip.decompress(path.read_bytes()) == BODY
    assert not list(tmp_path.glob("*.part"))


def test_not_modified_keeps_the_last_copy(tmp_path):
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(304)

    last = LastDownload("abc", "data/raw/old.gz", '"v1"', None)
    row = download_once(client_for(handler), "1", URL, tmp_path, last)
    assert seen["if-none-match"] == '"v1"'
    assert row["outcome"] == "unchanged"
    assert row["path"] == "data/raw/old.gz"


def test_same_checksum_deletes_the_new_copy(tmp_path):
    old = tmp_path / "old.gz"
    old.write_bytes(gzip.compress(BODY))
    last = LastDownload(hashlib.sha256(BODY).hexdigest(), old.as_posix(), None, None)
    day = tmp_path / "today"
    row = download_once(
        client_for(lambda r: httpx.Response(200, content=BODY)), "1", URL, day, last
    )
    assert row["outcome"] == "unchanged"
    assert row["path"] == old.as_posix()
    assert not list(day.glob("*.gz"))


def test_plain_403_retries_as_browser(tmp_path):
    def handler(request):
        if "Mozilla" in request.headers["user-agent"]:
            return httpx.Response(200, content=BODY)
        return httpx.Response(403)

    row = download_once(client_for(handler), "1", URL, tmp_path, None)
    assert row["outcome"] == "downloaded"
    assert row["access"] == "browser_ua_only"


def test_bot_challenge_is_not_worked_around(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, headers={"cf-mitigated": "challenge"})

    row = download_once(client_for(handler), "1", URL, tmp_path, None)
    assert row["outcome"] == "failed"
    assert len(calls) == 1


def test_server_errors_are_retried_then_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr("ingest.hospitals.download.time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, content=BODY)

    row = download(client_for(handler), "1", URL, tmp_path, None)
    assert row["outcome"] == "downloaded"
    assert len(calls) == 3

    always_down = client_for(lambda r: httpx.Response(503))
    row = download(always_down, "1", URL, tmp_path, None)
    assert row["outcome"] == "failed"
    assert "503" in row["error"]
