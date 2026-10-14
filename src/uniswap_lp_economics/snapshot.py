"""Read pool tick-book state from chain via Multicall3 (snapshot and validation samples)."""

import random

import polars as pl

from uniswap_lp_economics.config import N_FULL_BOOK, N_SAMPLES, POOL_ADDRESS, TICK_SPACING
from uniswap_lp_economics.rpc import (
    LIQUIDITY_CALL,
    SLOT0_CALL,
    RpcClient,
    decode_slot0,
    decode_ticks,
    decode_uint,
    tick_bitmap_call,
    ticks_call,
)
from uniswap_lp_economics.v3math import MAX_TICK, MIN_TICK

BATCH = 400
TICK_SCHEMA = {"tick": pl.Int64, "liquidity_gross": pl.Int128, "liquidity_net": pl.Int128}


def bitmap_word_range(
    tick_lo: int = MIN_TICK, tick_hi: int = MAX_TICK, spacing: int = TICK_SPACING
) -> range:
    return range((tick_lo // spacing) >> 8, ((tick_hi // spacing) >> 8) + 1)


def ticks_in_word(word_pos: int, bitmap: int, spacing: int = TICK_SPACING) -> list[int]:
    return [(word_pos * 256 + bit) * spacing for bit in range(256) if bitmap >> bit & 1]


def batched(
    client: RpcClient, calls: list[tuple[str, str]], block: int, allow_failure: bool = False
) -> list[str | None]:
    """Multicall in batches of BATCH. A failed sub-call raises, unless allow_failure (then None)."""
    out: list[str | None] = []
    for i in range(0, len(calls), BATCH):
        for result in client.multicall(calls[i : i + BATCH], block):
            if result is None and not allow_failure:
                raise RuntimeError(f"multicall sub-call failed at block {block}")
            out.append(result)
    return out


def _strict(client: RpcClient, calls: list[tuple[str, str]], block: int) -> list[str]:
    """batched() for callers that need every result: raises on failure, so no None remains."""
    return [r for r in batched(client, calls, block) if r is not None]


def read_state(client: RpcClient, block: int) -> dict[str, int]:
    slot0, liquidity = _strict(
        client, [(POOL_ADDRESS, SLOT0_CALL), (POOL_ADDRESS, LIQUIDITY_CALL)], block
    )
    return {"block": block, **decode_slot0(slot0), "liquidity": decode_uint(liquidity)}


def read_initialized_ticks(client: RpcClient, block: int, word_range: range) -> list[int]:
    words = list(word_range)
    results = _strict(client, [(POOL_ADDRESS, tick_bitmap_call(w)) for w in words], block)
    ticks: list[int] = []
    for w, result in zip(words, results, strict=True):
        ticks.extend(ticks_in_word(w, decode_uint(result)))
    return sorted(ticks)


def read_ticks(client: RpcClient, block: int, ticks: list[int]) -> pl.DataFrame:
    results = _strict(client, [(POOL_ADDRESS, ticks_call(t)) for t in ticks], block)
    rows = []
    for t, result in zip(ticks, results, strict=True):
        gross, net, initialized = decode_ticks(result)
        if not initialized:
            raise RuntimeError(f"tick {t} in bitmap but not initialized at block {block}")
        rows.append({"tick": t, "liquidity_gross": gross, "liquidity_net": net})
    return pl.DataFrame(rows, schema=TICK_SCHEMA)


def read_tick_book(client: RpcClient, block: int) -> tuple[pl.DataFrame, dict[str, int]]:
    meta = read_state(client, block)
    return read_ticks(
        client, block, read_initialized_ticks(client, block, bitmap_word_range())
    ), meta


def find_last_block_before(client: RpcClient, ts: int, lo: int, hi: int) -> int:
    """Largest block with timestamp < ts. Requires ts(lo) < ts <= ts(hi)."""
    if not client.block_timestamp(lo) < ts <= client.block_timestamp(hi):
        raise ValueError("search bounds do not bracket the timestamp")
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if client.block_timestamp(mid) < ts:
            lo = mid
        else:
            hi = mid
    return lo


def read_sample(
    client: RpcClient, block: int, n_ticks: int = 20, word_radius: int = 2
) -> tuple[dict[str, int], pl.DataFrame]:
    state = read_state(client, block)
    center = (state["tick"] // TICK_SPACING) >> 8
    initialized = read_initialized_ticks(
        client, block, range(center - word_radius, center + word_radius + 1)
    )
    nearest = sorted(sorted(initialized, key=lambda t: abs(t - state["tick"]))[:n_ticks])
    return state, read_ticks(client, block, nearest)


def pick_sample_blocks(
    first: int, last: int, n: int = N_SAMPLES, n_full: int = N_FULL_BOOK, seed: int = 42
) -> tuple[list[int], list[int]]:
    """n distinct blocks in [first, last] (sorted); n_full of them spread evenly (full-book)."""
    blocks = sorted(random.Random(seed).sample(range(first, last + 1), n))
    idx = [round(i * (n - 1) / (n_full - 1)) for i in range(n_full)]
    return blocks, [blocks[i] for i in idx]
