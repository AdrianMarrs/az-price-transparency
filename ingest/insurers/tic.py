"""Stream an insurer's Transparency in Coverage in-network file and keep Arizona hospitals.

Usage:
    uv run python -m ingest.insurers.tic --toc <index.json URL or path> --network arizona-hmo

A file is streamed from its URL, decompressed and parsed as it arrives; nothing is saved
except what's kept, and memory is bounded by the pieces in flight, not the file. Parsing is
ijson's C backend in pull mode building whole objects: a Python loop over every JSON event
was 4x slower, and ijson's push mode 2x slower.

Two passes over the stream. Pass 1 reads provider_references (groups of NPIs and tax IDs)
and keeps the groups containing an Arizona hospital. They normally come first, so pass 1
stops at the top-level "in_network" key and downloads only the start of the file. Pass 2
reads in_network (billing codes and their negotiated rates) and keeps the rates that
reference a kept group. A file that puts its references last is read whole twice.

Kept: provider groups containing an Arizona hospital's own NPI (warehouse/seeds/
hospital_npis.csv, role = hospital), and the rates that reference them. Written as JSON Lines,
one line per billing code, gzip-compressed, under data/insurers/raw/insurer=<name>/
month=<yyyy-mm>/ (and copied to the data bucket when DATA_BUCKET is set).
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
import tracemalloc
import zlib
from collections.abc import Iterator
from pathlib import Path

import httpx
import ijson
import polars as pl

from ingest.storage import upload

NPIS_PATH = Path("warehouse/seeds/hospital_npis.csv")
RAW_DIR = Path("data/insurers/raw")
USER_AGENT = "az-price-transparency/0.1 (+https://github.com/AdrianMarrs/az-price-transparency)"
CHUNK = 1 << 20  # download chunk (compressed)
JSON_CHUNK = 1 << 18  # decompressed piece handed to the parser


def hospital_npis(path: Path = NPIS_PATH) -> dict[int, str]:
    """NPI -> CCN for Arizona hospitals' own NPIs (not co-located practices)."""
    npis = pl.read_csv(path, infer_schema_length=0).filter(pl.col("role") == "hospital")
    return {int(r["npi"]): r["ccn"] for r in npis.iter_rows(named=True)}


def arizona_groups(reference: dict, npi_to_ccn: dict[int, str]) -> set[str]:
    """CCNs of the Arizona hospitals in one provider_references entry (empty if none)."""
    ccns = set()
    for group in reference.get("provider_groups", []):
        for npi in group.get("npi", []):
            if (ccn := npi_to_ccn.get(int(npi))) is not None:
                ccns.add(ccn)
    return ccns


def keep_rates(item: dict, kept: dict[int, set[str]], npi_to_ccn: dict[int, str] | None = None,
               stats: dict | None = None) -> dict | None:  # fmt: skip
    """The billing code with only the rates for kept providers, tagged with CCNs.

    A rate names its providers by reference to provider_references (what Cigna does), or
    lists them inline in its own provider_groups, which the schema also allows; inline
    groups are matched against npi_to_ccn and counted in stats["inline_group_rates"]."""
    rates = []
    for rate in item.get("negotiated_rates", []):
        refs = [r for r in rate.get("provider_references", []) if r in kept]
        ccns = set().union(*(kept[r] for r in refs))
        kept_rate = {"provider_references": refs} if refs else {}
        if "provider_groups" in rate:
            if stats is not None:
                stats["inline_group_rates"] = stats.get("inline_group_rates", 0) + 1
            if inline := arizona_groups(rate, npi_to_ccn or {}):
                ccns |= inline
                kept_rate["provider_groups"] = rate["provider_groups"]
        if ccns:
            rates.append({"ccns": sorted(ccns), **kept_rate,
                          "negotiated_prices": rate.get("negotiated_prices", [])})  # fmt: skip
    if not rates:
        return None
    return {k: v for k, v in item.items() if k != "negotiated_rates"} | {"negotiated_rates": rates}


def gunzip_chunks(chunks: Iterator[bytes]) -> Iterator[bytes]:
    """Decompress a gzip stream in pieces of at most JSON_CHUNK bytes. These files compress
    about 22x, so one 1 MB download chunk would otherwise become ~22 MB of JSON at once."""
    z = zlib.decompressobj(16 + zlib.MAX_WBITS)
    for chunk in chunks:
        data = chunk
        while data:
            if out := z.decompress(data, JSON_CHUNK):
                yield out
            data = z.unconsumed_tail
    if tail := z.flush():
        yield tail


def byte_chunks(source: str, client: httpx.Client | None = None) -> Iterator[bytes]:
    """Compressed bytes from a URL (streamed) or a local path."""
    if re.match(r"https?://", source):
        owns = client is None
        client = client or httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True,
                                        headers={"User-Agent": USER_AGENT})  # fmt: skip
        try:
            with client.stream("GET", source) as r:
                r.raise_for_status()
                yield from r.iter_bytes(CHUNK)
        finally:
            if owns:
                client.close()
    else:
        with open(source, "rb") as f:
            while chunk := f.read(CHUNK):
                yield chunk


REFS_KEY, RATES_KEY = b'"provider_references"', b'"in_network"'


def stream_file(source: str, npi_to_ccn: dict[int, str], client=None, stats: dict | None = None):
    """Yield kept billing codes from one in-network file (see the module docstring)."""
    stats = stats if stats is not None else {}
    stats.update(
        references=0, kept_groups=0, codes=0, kept_codes=0, compressed=0, inline_group_rates=0
    )

    def counted(chunks):
        for chunk in chunks:
            stats["compressed"] += len(chunk)
            yield chunk

    # Pass 1: provider groups. When they come first, this reads only up to "in_network".
    kept: dict[int, set[str]] = {}
    reader = UpToRates(counted(byte_chunks(source, client)))
    try:
        for ref in ijson.items(reader, "provider_references.item", use_float=True,
                               buf_size=JSON_CHUNK):  # fmt: skip
            stats["references"] += 1
            if ccns := arizona_groups(ref, npi_to_ccn):
                kept[ref["provider_group_id"]] = ccns
    finally:
        reader.close()
    stats["kept_groups"] = len(kept)
    stats["refs_first"] = reader.cut
    stats["pass1_compressed"] = stats["compressed"]

    # Pass 2: the rates, keeping those for a kept group. Read even when pass 1 kept no
    # groups: a rate can list its providers inline instead of by reference.
    reader = GunzipReader(counted(byte_chunks(source, client)))
    try:
        for item in ijson.items(reader, "in_network.item", use_float=True, buf_size=JSON_CHUNK):
            stats["codes"] += 1
            if (kept_item := keep_rates(item, kept, npi_to_ccn, stats)) is not None:
                stats["kept_codes"] += 1
                yield kept_item
    finally:
        reader.close()


class FirstKey:
    """Which of two byte strings occurs first in a stream fed chunk by chunk."""

    def __init__(self, *needles: bytes):
        self.needles, self.first, self.tail = needles, None, b""
        self.keep = max(len(n) for n in needles) - 1

    def feed(self, data: bytes) -> bytes | None:
        if self.first is None:
            window = self.tail + data  # a needle may straddle two chunks
            hits = [(i, n) for n in self.needles if (i := window.find(n)) >= 0]
            if hits:
                self.first = min(hits)[1]
            self.tail = window[-self.keep :]
        return self.first


class GunzipReader:
    """A file-like view of gunzip_chunks, for ijson's pull API (which runs entirely in C, about
    twice as fast as feeding its push API)."""

    def __init__(self, chunks: Iterator[bytes]):
        self.source, self.buf = chunks, bytearray()
        self.chunks = gunzip_chunks(chunks)

    def read(self, n: int = CHUNK) -> bytes:
        while len(self.buf) < n and (chunk := next(self.chunks, None)) is not None:
            self.buf += chunk
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def close(self) -> None:
        """Stop downloading (closes the HTTP stream if reading stopped early)."""
        self.chunks.close()
        if hasattr(self.source, "close"):
            self.source.close()


class UpToRates(GunzipReader):
    """The decompressed JSON, ended early when the provider references come first: cut at the
    top-level "in_network" key and closed with `"in_network":[]}`, so the parser sees a
    complete document and the rest of the file is never downloaded. When the rates come
    first it passes the whole file through. The order is decided by FirstKey: a nested
    "provider_references" (inside a rate) can only occur after "in_network" has begun."""

    def __init__(self, chunks: Iterator[bytes]):
        super().__init__(chunks)
        self.order, self.done, self.cut = FirstKey(REFS_KEY, RATES_KEY), False, False
        self.hold = len(RATES_KEY) - 1  # never hand out bytes a key could still straddle

    def read(self, n: int = CHUNK) -> bytes:
        while not self.done and len(self.buf) < n + self.hold:
            chunk = next(self.chunks, None)
            if chunk is None:
                self.done = True
                break
            start = max(0, len(self.buf) - self.hold)
            self.buf += chunk
            if self.order.first is None:
                self.order.feed(chunk)
            if self.order.first == REFS_KEY and (i := self.buf.find(RATES_KEY, start)) >= 0:
                del self.buf[i:]
                self.buf += RATES_KEY + b":[]}"
                self.done = self.cut = True
        take = n if self.done else min(n, max(0, len(self.buf) - self.hold))
        out = bytes(self.buf[:take])
        del self.buf[:take]
        return out


def in_network_files(toc: dict, network: str) -> list[str]:
    """Distinct in-network file URLs whose name contains `network`."""
    urls = {}
    for s in toc["reporting_structure"]:
        for f in s.get("in_network_files", []):
            if network in f["location"].split("?")[0].rsplit("/", 1)[-1]:
                urls.setdefault(f["location"].split("?")[0], f["location"])
    return list(urls.values())


def output_path(insurer: str, month: str, url: str) -> Path:
    name = url.split("?")[0].rsplit("/", 1)[-1].removesuffix(".gz").removesuffix(".json")
    return RAW_DIR / f"insurer={insurer}" / f"month={month}" / f"{name}.jsonl.gz"


def run_file(url: str, insurer: str, month: str, npi_to_ccn: dict[int, str],
             trace_memory: bool = False) -> dict:  # fmt: skip
    """Stream one file to its JSON Lines output; returns stats with timing (and peak Python
    memory with trace_memory, which slows the run: tracemalloc hooks every allocation)."""
    dest = output_path(insurer, month, url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stats: dict = {}
    if trace_memory:
        tracemalloc.start()
    started = time.perf_counter()
    part = dest.with_name(dest.name + ".part")
    with gzip.open(part, "wt", encoding="utf-8") as out:
        for item in stream_file(url, npi_to_ccn, stats=stats):
            out.write(json.dumps(item, separators=(",", ":")) + "\n")
    part.replace(dest)
    seconds = time.perf_counter() - started
    peak = tracemalloc.get_traced_memory()[1] if trace_memory else 0
    if trace_memory:
        tracemalloc.stop()
    stats |= {"file": dest.name, "seconds": round(seconds, 1), "peak_mb": round(peak / 1e6, 1) if trace_memory else None,
              "mb_per_s": round(stats["compressed"] / 1e6 / seconds, 2), "path": dest.as_posix(),
              "s3_uri": upload(dest)}  # fmt: skip
    return stats


def load_toc(source: str) -> dict:
    if re.match(r"https?://", source):
        with httpx.Client(
            timeout=120, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        ) as c:
            return c.get(source).json()
    return json.loads(Path(source).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--toc", required=True, help="table-of-contents URL or local path")
    parser.add_argument("--network", required=True, help="part of the in-network file name")
    parser.add_argument("--insurer", default="cigna")
    parser.add_argument("--month", default=time.strftime("%Y-%m"))
    parser.add_argument("--trace-memory", action="store_true", help="report peak memory (slower)")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    npi_to_ccn = hospital_npis()
    urls = in_network_files(load_toc(args.toc), args.network)
    print(f"{len(urls)} file(s) match {args.network!r}; {len(npi_to_ccn)} hospital NPIs")
    for url in urls:
        print(json.dumps(run_file(url, args.insurer, args.month, npi_to_ccn, args.trace_memory)))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    main()
