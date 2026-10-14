"""Price discovery (spec 6): per-block pool vs Binance series, basis, gap episodes, lead-lag
and available-vs-captured arbitrage."""

from typing import Any

import polars as pl

from uniswap_lp_economics.align import reference_at
from uniswap_lp_economics.config import FEE_PIPS
from uniswap_lp_economics.replay import iter_block_starts
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import sqrt_price_x96_to_eth_price
from uniswap_lp_economics.v3swap import arb_to_price

FEE_BAND_BP = 5.0
EPISODE_THRESHOLDS_BP = (5.0, 10.0)
CEX_FEE_SENSITIVITY_BP = 1.0
SERIES_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "block_timestamp": pl.Datetime("us", "UTC"),
    "ts_us": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "tick": pl.Int64,
    "liquidity": pl.Int128,
    "pool_price": pl.Float64,
    "end_sqrt_price_x96": pl.Int128,
    "end_tick": pl.Int64,
    "end_liquidity": pl.Int128,
    "end_pool_price": pl.Float64,
    "p_cex": pl.Float64,
    "cex_age_s": pl.Float64,
    "arb_direction": pl.String,
    "available_usd": pl.Float64,
    "available_usd_cex1bp": pl.Float64,
}


def build_block_series(
    events: pl.DataFrame,
    book: TickBook,
    fee_protocol: int,
    blocks: pl.DataFrame,
    ref: pl.DataFrame,
    end_us: int,
    fee_pips: int = FEE_PIPS,
) -> pl.DataFrame:
    """One row per block in `blocks` (spec 6.1), with the arbitrage available at its start.

    `book` must hold the pool state at the start of the first block; it is advanced through
    `events` in place. A block missing from `blocks` gets no row (check A2 reports it).
    """
    blocks = blocks.sort("block_number")
    if blocks.height == 0:
        raise ValueError("no blocks to build a series from")
    numbers = blocks["block_number"].to_list()
    ts_us = blocks["block_timestamp"].dt.epoch("us")
    refs = reference_at(ts_us, ref, end_us)
    info = {
        b: (stamp, t, p, age)
        for b, stamp, t, p, age in zip(
            numbers,
            blocks["block_timestamp"].to_list(),
            ts_us.to_list(),
            refs["price"].to_list(),
            refs["age_s"].to_list(),
            strict=True,
        )
    }
    cols: dict[str, list[Any]] = {name: [] for name in SERIES_SCHEMA}
    pending = False
    for b in iter_block_starts(events, book, fee_protocol, numbers[0], numbers[-1]):
        if pending:  # this block's start is the previous block's end
            cols["end_sqrt_price_x96"].append(book.sqrt_price_x96)
            cols["end_tick"].append(book.tick)
            cols["end_liquidity"].append(book.liquidity)
            cols["end_pool_price"].append(sqrt_price_x96_to_eth_price(book.sqrt_price_x96))
            pending = False
        if b not in info:
            continue
        stamp, t, p, age = info[b]
        direction: str | None = None
        avail: float | None = None
        avail_fee: float | None = None
        if p is not None:
            a0 = arb_to_price(book, p, fee_pips)
            a1 = (
                a0
                if a0.direction == "none"
                else arb_to_price(book, p, fee_pips, CEX_FEE_SENSITIVITY_BP)
            )
            direction, avail, avail_fee = a0.direction, a0.profit_usd, a1.profit_usd
        values: dict[str, Any] = {
            "block_number": b,
            "block_timestamp": stamp,
            "ts_us": t,
            "sqrt_price_x96": book.sqrt_price_x96,
            "tick": book.tick,
            "liquidity": book.liquidity,
            "pool_price": sqrt_price_x96_to_eth_price(book.sqrt_price_x96),
            "p_cex": p,
            "cex_age_s": age,
            "arb_direction": direction,
            "available_usd": avail,
            "available_usd_cex1bp": avail_fee,
        }
        for name, value in values.items():
            cols[name].append(value)
        pending = True

    counts = events.group_by("block_number").agg(
        n_events=pl.len().cast(pl.Int64),
        n_swaps=(pl.col("event") == "swap").sum().cast(pl.Int64),
    )
    return (
        pl.DataFrame(cols, schema=SERIES_SCHEMA)
        .join(counts, on="block_number", how="left", maintain_order="left")
        .with_columns(
            pl.col("n_events").fill_null(0),
            pl.col("n_swaps").fill_null(0),
            basis_bp=(pl.col("pool_price") / pl.col("p_cex")).log() * 1e4,
        )
    )
