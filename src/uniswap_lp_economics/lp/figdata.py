"""Small tables the figures need beyond the results tables (chart redesign spec section 4): the
stale-pool episode of figure 2 and the JIT block of figure 11, each picked by a fixed rule."""

from typing import Any

import numpy as np
import polars as pl

from uniswap_lp_economics.config import BLOCK_TIME_S, US
from uniswap_lp_economics.v3math import sqrt_price_x96_to_eth_price

EPISODE_MOVE_BLOCKS = 20
EPISODE_BEFORE = 4
EPISODE_LENGTH = 32
JIT_BLOCK_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "event": pl.String,
    "role": pl.String,
    "tx_hash": pl.String,
    "amount_usdc": pl.Float64,
    "amount_eth": pl.Float64,
    "pool_price_after": pl.Float64,
    "notional_usd": pl.Float64,
    "markout_usd_0": pl.Float64,
    "fee_usd": pl.Float64,
    "lvr_0_usd": pl.Float64,
    "position_id": pl.String,
    "full_pattern": pl.Boolean,
}


def episode_window(daily: pl.DataFrame, blocks_state: pl.DataFrame) -> pl.DataFrame:
    """On the day with the largest measured LVR (0 s; the earliest such day on ties), the 20-block
    stretch with the largest absolute Binance log move; the window starts 4 blocks before it and
    runs 32 blocks (fewer at the day's edges)."""
    day = daily.sort(["lvr_0", "day"], descending=[True, False])["day"][0]
    bs = (
        blocks_state.sort("block_number")
        .with_columns(_day=pl.from_epoch("ts_us", time_unit="us").dt.date())
        .filter(pl.col("_day") == day)
        .drop("_day")
    )
    if bs.height == 0:
        raise ValueError(f"no blocks on {day}, the day with the largest LVR")
    logp = np.log(bs["p_cex"].to_numpy().astype(float))
    w = min(EPISODE_MOVE_BLOCKS, bs.height - 1)
    i0 = 0
    if w > 0:
        move = np.nan_to_num(np.abs(logp[w:] - logp[:-w]), nan=-1.0)
        i0 = int(np.argmax(move))
    return bs.slice(max(i0 - EPISODE_BEFORE, 0), EPISODE_LENGTH)


def episode_tables(
    daily: pl.DataFrame, blocks_state: pl.DataFrame, steps: pl.DataFrame, trades: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Figure 2's data: per block of the window, the pool price after the block, Binance at block
    time, LVR (0 s) over the block's steps and whether a searcher swapped; and Binance's last trade
    in each second of the window."""
    win = episode_window(daily, blocks_state)
    per_block = (
        steps.filter(pl.col("block_number").is_in(win["block_number"].implode()))
        .group_by("block_number")
        .agg(
            lvr_0_usd=pl.col("lvr_0").sum(),
            has_searcher=(pl.col("flow_label") == "searcher").any(),
        )
    )
    prices = [sqrt_price_x96_to_eth_price(int(s)) for s in win["end_sqrt_price_x96"].to_list()]
    blocks = (
        win.select("block_number", "ts_us", "p_cex")
        .with_columns(pool_price=pl.Series(prices, dtype=pl.Float64))
        .join(per_block, on="block_number", how="left")
        .with_columns(pl.col("lvr_0_usd").fill_null(0.0), pl.col("has_searcher").fill_null(False))
        .select("block_number", "ts_us", "pool_price", "p_cex", "lvr_0_usd", "has_searcher")
        .sort("block_number")
    )
    t0 = int(win["ts_us"][0])
    t1 = int(win["ts_us"][-1]) + BLOCK_TIME_S * US
    cex = (
        trades.filter((pl.col("ts_us") >= t0) & (pl.col("ts_us") < t1))
        .sort("ts_us")
        .group_by((pl.col("ts_us") // US).alias("sec"), maintain_order=True)
        .agg(pl.col("price").last())
        .select(ts_us=pl.col("sec") * US, price=pl.col("price").cast(pl.Float64))
        .sort("ts_us")
    )
    return blocks, cex


def select_jit_position(
    positions: pl.DataFrame, flows_window: pl.DataFrame, swaps: pl.DataFrame
) -> tuple[str | None, bool]:
    """Figure 11's position: among JIT positions whose own transactions also swap in the pool both
    before the first add and after the last removal, the one with the largest P&L vs rebalancing
    (then lowest block, then id). Without such a position, the most profitable JIT position, with
    the flag False; without JIT positions, (None, False)."""
    jit = positions.filter(pl.col("lp_type") == "jit").select(
        "position_id", "pnl_rebal_usd", "start_block"
    )
    if jit.height == 0:
        return None, False
    f = flows_window.join(jit.select("position_id"), on="position_id", how="semi")
    span = f.group_by("position_id").agg(
        first_add=pl.col("pool_log_index").filter(pl.col("liquidity_delta") > 0).min(),
        last_remove=pl.col("pool_log_index").filter(pl.col("liquidity_delta") < 0).max(),
    )
    own = (
        f.select("position_id", "tx_hash", "block_number")
        .unique()
        .join(swaps.select("tx_hash", "log_index", "block_number"), on=["tx_hash", "block_number"])
    )
    pattern = (
        own.join(span, on="position_id")
        .group_by("position_id")
        .agg(
            before=(pl.col("log_index") < pl.col("first_add")).any(),
            after=(pl.col("log_index") > pl.col("last_remove")).any(),
        )
        .filter(pl.col("before") & pl.col("after"))
    )
    full = jit.join(pattern.select("position_id"), on="position_id", how="semi")
    pool, flag = (full, True) if full.height else (jit, False)
    best = pool.sort(
        ["pnl_rebal_usd", "start_block", "position_id"], descending=[True, False, False]
    ).row(0, named=True)
    return str(best["position_id"]), flag


def jit_block_table(
    positions: pl.DataFrame,
    flows_window: pl.DataFrame,
    swaps: pl.DataFrame,
    events: pl.DataFrame,
    steps: pl.DataFrame,
    blocks_state: pl.DataFrame,
) -> pl.DataFrame:
    """Figure 11's data: every pool event of the selected JIT position's block in log order, with
    its role (`jit` = the position's own liquidity events, `operator` = other events in the
    position's transactions, `other`), the pool price after it and the swaps' USD flows."""
    pid, full = select_jit_position(positions, flows_window, swaps)
    if pid is None:
        return pl.DataFrame(schema=JIT_BLOCK_SCHEMA)
    f = flows_window.filter(pl.col("position_id") == pid)
    block = int(f["block_number"][0])
    txs = set(f["tx_hash"].to_list())
    own_logs = set(f["pool_log_index"].to_list())
    start = blocks_state.filter(pl.col("block_number") == block)["sqrt_price_x96"][0]
    price = sqrt_price_x96_to_eth_price(int(start))
    rows = []
    for e in events.filter(pl.col("block_number") == block).sort("log_index").iter_rows(named=True):
        if e["event"] == "swap" and e["sqrt_price_x96"] is not None:
            price = sqrt_price_x96_to_eth_price(int(e["sqrt_price_x96"]))
        role = (
            "jit" if e["log_index"] in own_logs else "operator" if e["tx_hash"] in txs else "other"
        )
        rows.append(
            {
                "block_number": block,
                "log_index": e["log_index"],
                "event": e["event"],
                "role": role,
                "tx_hash": e["tx_hash"],
                "amount_usdc": int(e["amount0"] or 0) / 1e6,
                "amount_eth": int(e["amount1"] or 0) / 1e18,
                "pool_price_after": price,
                "position_id": pid,
                "full_pattern": full,
            }
        )
    base = pl.DataFrame(rows).with_columns(pl.col("log_index").cast(pl.Int64))
    sw = swaps.filter(pl.col("block_number") == block).select(
        pl.col("log_index").cast(pl.Int64), "notional_usd", "markout_usd_0"
    )
    st = (
        steps.filter(pl.col("block_number") == block)
        .group_by(pl.col("log_index").cast(pl.Int64))
        .agg(fee_usd=pl.col("fee_usd").sum(), lvr_0_usd=pl.col("lvr_0").sum())
    )
    out = base.join(sw, on="log_index", how="left").join(st, on="log_index", how="left")
    return out.select(list(JIT_BLOCK_SCHEMA)).cast(pl.Schema(JIT_BLOCK_SCHEMA)).sort("log_index")
