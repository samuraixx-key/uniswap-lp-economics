from pathlib import Path
from typing import Any

import httpx
import polars as pl

from uniswap_lp_economics.data import block_timing, relays

R1, R2 = "https://relay-one.example", "https://relay-two.example"
SLOT = 100
SLOT_START_MS = (block_timing.GENESIS_TIME_S + 12 * SLOT) * 1000


def relay_world(answers: dict[str, dict[str, Any]]) -> httpx.Client:
    """answers[relay_base][path] -> JSON body (or an httpx.Response) for every block."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = answers[f"{request.url.scheme}://{request.url.host}"][request.url.path]
        return body if isinstance(body, httpx.Response) else httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


DELIVERED = [{"block_hash": "0xaa", "slot": str(SLOT), "value": "1"}]
BIDS = [
    {"block_hash": "0xbb", "slot": str(SLOT), "timestamp_ms": str(SLOT_START_MS + 100)},
    {"block_hash": "0xaa", "slot": str(SLOT), "timestamp_ms": str(SLOT_START_MS + 1100)},
    {"block_hash": "0xaa", "slot": str(SLOT), "timestamp_ms": str(SLOT_START_MS + 944)},
]


def test_winning_bid_offset_from_slot_start() -> None:
    client = relay_world({R1: {relays.PATH: DELIVERED, block_timing.BIDS_PATH: BIDS}})
    row = block_timing.time_block(client, 7, (R1,), backoff_s=0)
    assert row["found"] and row["relay"] == R1 and row["slot"] == SLOT
    assert row["block_hash"] == "0xaa" and row["offset_ms"] == 944  # earliest bid with the hash
    assert row["bid_ms"] == SLOT_START_MS + 944


def test_hash_missing_from_bids_is_not_found() -> None:
    client = relay_world({R1: {relays.PATH: DELIVERED, block_timing.BIDS_PATH: BIDS[:1]}})
    row = block_timing.time_block(client, 7, (R1,), backoff_s=0)
    assert not row["found"] and row["relay"] == R1 and row["offset_ms"] is None


def test_tries_relays_in_order_and_skips_ones_without_the_block() -> None:
    client = relay_world(
        {
            R1: {relays.PATH: [], block_timing.BIDS_PATH: []},
            R2: {relays.PATH: DELIVERED, block_timing.BIDS_PATH: BIDS},
        }
    )
    row = block_timing.time_block(client, 7, (R1, R2), backoff_s=0)
    assert row["found"] and row["relay"] == R2


def test_a_failing_relay_is_listed_as_unchecked() -> None:
    client = relay_world({R1: {relays.PATH: httpx.Response(503)}})
    row = block_timing.time_block(client, 7, (R1,), backoff_s=0)
    assert not row["found"] and row["relays_unchecked"] == R1


def test_fetch_resumes_and_adds_a_second_batch_below_the_minimum(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == relays.PATH:
            calls.append(int(request.url.params["block_number"]))
        return httpx.Response(200, json=[])  # nothing delivered: never timed

    client = httpx.Client(transport=httpx.MockTransport(handler))
    path = block_timing.fetch_block_timing(
        tmp_path, 1, 1000, client=client, relay_urls=(R1,), n=5, min_timed=1
    )
    first = set(relays.sample_blocks(1, 1000, 5, seed=42))
    second = set(relays.sample_blocks(1, 1000, 5, seed=43))
    assert set(calls) == first | second  # below the minimum: the second batch was tried
    assert pl.read_parquet(path).height == len(first | second)
    block_timing.fetch_block_timing(
        tmp_path, 1, 1000, client=client, relay_urls=(R1,), n=5, min_timed=1
    )
    assert len(calls) == len(first | second)  # nothing re-queried


def test_timing_summary() -> None:
    rows = pl.DataFrame(
        {
            "block_number": [1, 2, 3, 4],
            "relay": [R1, R1, R2, None],
            "found": [True, True, True, False],
            "offset_ms": [900, 1000, 1500, None],
        }
    )
    s = block_timing.timing_summary(rows)
    assert s["n_timed"] == 3 and s["n_queried"] == 4 and s["p50_ms"] == 1000
    assert s["by_relay"] == [
        {"relay": R1, "n": 2, "p50_ms": 950.0},
        {"relay": R2, "n": 1, "p50_ms": 1500.0},
    ]
    none = block_timing.timing_summary(rows.filter(~pl.col("found")))
    assert none["n_timed"] == 0 and none["p10_ms"] is None and none["by_relay"] == []
