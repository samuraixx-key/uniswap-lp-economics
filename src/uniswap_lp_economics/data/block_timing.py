"""When blocks were actually sealed (sub-project 4 spec 5.5): the winning bid's received time
relative to slot start, from the relays that still publish July 2026 bids.

Free public endpoints. Per block: the relay's delivered payload gives the winning block hash and
the slot; the relay's received bids for that block give the time the winning block arrived.
Ultrasound, the largest relay, keeps no bid history for the window, so the sample covers only
blocks delivered through `config.TIMING_RELAYS`. Resumable like the relay sample.
"""

from pathlib import Path
from typing import Any

import httpx
import polars as pl

from uniswap_lp_economics.config import N_RELAY_SAMPLES, TIMING_RELAYS
from uniswap_lp_economics.data.relays import PATH, RelayBreaker, _get, sample_blocks
from uniswap_lp_economics.io import read_exact, write_exact

TIMING_FILE = "block_timing.parquet"
BIDS_PATH = "/relay/v1/data/bidtraces/builder_blocks_received"
GENESIS_TIME_S = 1_606_824_023  # beacon chain genesis; slot s starts at genesis + 12 s
MIN_TIMED = 150  # below this after the first batch, a second batch is tried (plan Ruling 4)
TIMING_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "relay": pl.String,  # the relay that delivered the block, when one did
    "found": pl.Boolean,  # the winning bid was timed
    "slot": pl.Int64,
    "block_hash": pl.String,
    "bid_ms": pl.Int64,
    "offset_ms": pl.Int64,
    "relays_unchecked": pl.String,  # relays that failed for this block (comma-separated)
}


def _row(block: int, **kw: Any) -> dict[str, Any]:
    return {**dict.fromkeys(TIMING_SCHEMA), "block_number": block, "found": False, **kw}


def time_block(
    client: httpx.Client,
    block: int,
    relays: tuple[str, ...] = TIMING_RELAYS,
    backoff_s: float = 1.0,
    breaker: RelayBreaker | None = None,
) -> dict[str, Any]:
    """The first relay (in order) that delivered the block, and its winning bid's offset from
    slot start (the earliest received bid with the delivered hash); else a not-found row."""
    unchecked: list[str] = []
    for relay in relays:
        if breaker is not None and relay in breaker.skipped:
            unchecked.append(relay)
            continue
        payloads = _get(client, relay + PATH, block, backoff_s)
        bids = _get(client, relay + BIDS_PATH, block, backoff_s) if payloads else payloads
        if breaker is not None:
            breaker.record(relay, bids is None)
        if bids is None:
            unchecked.append(relay)
            continue
        if not payloads:
            continue
        winner, slot = str(payloads[0]["block_hash"]), int(payloads[0]["slot"])
        times = [int(b["timestamp_ms"]) for b in bids if b.get("block_hash") == winner]
        if not times:  # delivered here, but the winning bid is not in the relay's history
            return _row(block, relay=relay, slot=slot, block_hash=winner)
        bid_ms = min(times)
        return _row(
            block,
            relay=relay,
            found=True,
            slot=slot,
            block_hash=winner,
            bid_ms=bid_ms,
            offset_ms=bid_ms - (GENESIS_TIME_S + 12 * slot) * 1000,
        )
    return _row(block, relays_unchecked=",".join(unchecked) if unchecked else None)


def fetch_block_timing(
    raw_dir: Path,
    first: int,
    last: int,
    client: httpx.Client | None = None,
    relay_urls: tuple[str, ...] = TIMING_RELAYS,
    n: int = N_RELAY_SAMPLES,
    min_timed: int = MIN_TIMED,
) -> Path:
    """Time the relay sample's blocks (seed 42); if fewer than `min_timed` are timed, also a
    second batch of `n` (seed 43). Blocks already in the file are not re-queried."""
    out = raw_dir / TIMING_FILE
    raw_dir.mkdir(parents=True, exist_ok=True)
    done = read_exact(out) if out.exists() else pl.DataFrame(schema=TIMING_SCHEMA)
    rows: list[dict[str, Any]] = []
    breaker = RelayBreaker()
    own = client is None
    http = client or httpx.Client(follow_redirects=True)

    def table() -> pl.DataFrame:
        return pl.concat([done, pl.DataFrame(rows, schema=TIMING_SCHEMA)])

    try:
        for seed in (42, 43):
            current = table()
            if seed != 42 and int(current["found"].sum()) >= min_timed:
                break
            seen = set(current["block_number"].to_list())
            todo = [b for b in sample_blocks(first, last, n, seed=seed) if b not in seen]
            for i, b in enumerate(todo):
                rows.append(time_block(http, b, relay_urls, breaker=breaker))
                if (i + 1) % 100 == 0:
                    write_exact(table(), out)
                    print(f"  seed {seed}: {i + 1}/{len(todo)} blocks")
    finally:
        # Also on an error or interrupt: keep every block queried so far.
        if rows or not out.exists():
            write_exact(table(), out)
        if own:
            http.close()
    return out


def timing_summary(timing: pl.DataFrame) -> dict[str, Any]:
    """Winning-bid offsets (ms after slot start): 10th, 50th and 90th percentiles, pooled and
    the median per relay. Quantiles are None when nothing was timed."""
    timed = timing.filter(pl.col("found"))
    off = timed["offset_ms"].cast(pl.Float64)

    def q(p: float) -> float | None:
        return float(off.quantile(p, "linear")) if timed.height else None  # type: ignore[arg-type]

    by = (
        timed.group_by("relay")
        .agg(n=pl.len(), p50_ms=pl.col("offset_ms").cast(pl.Float64).quantile(0.5, "linear"))
        .sort("relay")
    )
    return {
        "n_timed": timed.height,
        "n_queried": timing.height,
        "p10_ms": q(0.1),
        "p50_ms": q(0.5),
        "p90_ms": q(0.9),
        "by_relay": [{**r, "n": int(r["n"])} for r in by.to_dicts()],
    }
