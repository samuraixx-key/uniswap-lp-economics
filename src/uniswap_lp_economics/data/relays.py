"""Relay-reported proposer payments for a random sample of window blocks (spec D6).

Free public endpoints (`proposer_payload_delivered`); used only to cross-check the on-chain
proposer payment (a reported check). Resumable: blocks already in the file are not re-queried.
"""

import random
import time
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from uniswap_lp_economics.config import N_RELAY_SAMPLES, RELAYS
from uniswap_lp_economics.io import read_exact, write_exact

RELAY_FILE = "relays.parquet"
PATH = "/relay/v1/data/bidtraces/proposer_payload_delivered"
RELAY_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "relay": pl.String,
    "found": pl.Boolean,
    "value_wei": pl.Int128,
    "proposer_fee_recipient": pl.String,
    "builder_pubkey": pl.String,
}
_RETRIES = 3


def sample_blocks(first: int, last: int, n: int, seed: int = 42) -> list[int]:
    return sorted(random.Random(seed).sample(range(first, last + 1), n))


def _get(client: httpx.Client, url: str, block: int, backoff_s: float) -> list[Any]:
    """The relay's payload list for a block; [] when absent, refused or still failing."""
    for attempt in range(_RETRIES):
        try:
            r = client.get(url, params={"block_number": block}, timeout=30)
        except httpx.RequestError:
            r = None
        if r is not None and r.status_code == 200:
            body = r.json()
            return body if isinstance(body, list) else []
        if r is not None and r.status_code != 429 and r.status_code < 500:
            return []
        time.sleep(backoff_s * 2**attempt)
    return []


def query_block(
    client: httpx.Client, block: int, relays: tuple[str, ...] = RELAYS, backoff_s: float = 1.0
) -> dict[str, Any]:
    """The first relay (in order) that delivered the block's payload, else a not-found row."""
    for relay in relays:
        payloads = _get(client, relay + PATH, block, backoff_s)
        if payloads:
            p = payloads[0]
            return {
                "block_number": block,
                "relay": relay,
                "found": True,
                "value_wei": int(p["value"]),
                "proposer_fee_recipient": str(p.get("proposer_fee_recipient", "")).lower(),
                "builder_pubkey": p.get("builder_pubkey"),
            }
    return {
        "block_number": block,
        "relay": None,
        "found": False,
        "value_wei": None,
        "proposer_fee_recipient": None,
        "builder_pubkey": None,
    }


def fetch_relay_sample(
    raw_dir: Path,
    first: int,
    last: int,
    n: int = N_RELAY_SAMPLES,
    client: httpx.Client | None = None,
    relay_urls: tuple[str, ...] = RELAYS,
) -> Path:
    out = raw_dir / RELAY_FILE
    raw_dir.mkdir(parents=True, exist_ok=True)
    done = read_exact(out) if out.exists() else pl.DataFrame(schema=RELAY_SCHEMA)
    seen = set(done["block_number"].to_list())
    todo = [b for b in sample_blocks(first, last, n) if b not in seen]
    rows: list[dict[str, Any]] = []
    own = client is None
    http = client or httpx.Client(follow_redirects=True)
    try:
        for i, b in enumerate(todo):
            rows.append(query_block(http, b, relay_urls))
            if (i + 1) % 100 == 0:
                write_exact(pl.concat([done, pl.DataFrame(rows, schema=RELAY_SCHEMA)]), out)
                print(f"  {i + 1}/{len(todo)} blocks")
    finally:
        if own:
            http.close()
    write_exact(pl.concat([done, pl.DataFrame(rows, schema=RELAY_SCHEMA)]), out)
    return out
