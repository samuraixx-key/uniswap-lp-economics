"""A price-taker position's share of recorded swap steps (spec 5.1).

Within a step, liquidity is constant and amounts between two sqrt prices follow the V3 delta
formulas, so a range whose bounds fall inside a step takes the part of the step between them.
"""

import polars as pl

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick

_K = 2**20  # (block, log) order key = block * _K + log; a block's logs stay far below 2**20
OPEN_BLOCK = 2**40  # end block of a stretch still held when the history ends
_Q96 = float(2**96)


def order_key(block: str, log: str) -> pl.Expr:
    """(block, log index) as one Int64 that sorts the same way; log -1 (an arb) comes first."""
    return pl.col(block) * _K + pl.col(log)


def _per_liquidity(lo: pl.Expr, hi: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """(USDC, WETH) per unit of liquidity between two X96 sqrt prices.

    1/x - 1/y is taken as (y - x) / (x y) with y - x exact in integers, so a short step keeps
    its digits."""
    x, y = lo.cast(pl.Float64) / _Q96, hi.cast(pl.Float64) / _Q96
    d = (hi - lo).cast(pl.Float64) / _Q96
    return d / (x * y) / 10**DECIMALS0, d / 10**DECIMALS1


def attribute(steps: pl.DataFrame, held: pl.DataFrame) -> pl.DataFrame:
    """Each step's fee_usd and lvr_0 earned by `held` (spec 5.1), one row per attributed step.

    `held` rows (seg, start/end block and log, tick_lower, tick_upper, liquidity) hold over
    [(start_block, start_log), (end_block, end_log)) and must not overlap. A step that does not
    move (a flash) is in range iff tick_lower <= tick_start < tick_upper, as fee growth counts
    it; a step inside the range takes its recorded values x liquidity / L; one that crosses a
    bound takes the part between the bounds from the V3 delta formulas."""
    pa = [get_sqrt_ratio_at_tick(t) for t in held["tick_lower"].to_list()]
    pb = [get_sqrt_ratio_at_tick(t) for t in held["tick_upper"].to_list()]
    h = held.select(
        "seg",
        "tick_lower",
        "tick_upper",
        _start=order_key("start_block", "start_log"),
        _end=order_key("end_block", "end_log"),
        _ell=pl.col("liquidity").cast(pl.Float64),
        _pa=pl.Series(pa, dtype=pl.Int128),
        _pb=pl.Series(pb, dtype=pl.Int128),
    ).sort("_start")
    if (h["_start"].shift(-1) < h["_end"]).any():
        raise ValueError("held rows overlap in (block, log) order")
    j = (
        steps.filter(pl.col("accrued"))
        .with_columns(_key=order_key("block_number", "log_index"))
        .sort("_key", "step")
        .set_sorted("_key")
        .join_asof(h, left_on="_key", right_on="_start", strategy="backward")
        .filter(pl.col("_key") < pl.col("_end"))
    )
    lo = pl.min_horizontal("sqrt_start", "sqrt_end")
    hi = pl.max_horizontal("sqrt_start", "sqrt_end")
    pa_, pb_, ell, p0 = pl.col("_pa"), pl.col("_pb"), pl.col("_ell"), pl.col("p0")
    flat = lo == hi
    whole = flat | ((pa_ <= lo) & (hi <= pb_))
    share = ell / pl.col("liquidity").cast(pl.Float64)
    usdc, eth = _per_liquidity(pl.max_horizontal(lo, pa_), pl.min_horizontal(hi, pb_))
    usdc_step, eth_step = _per_liquidity(lo, hi)
    zfo = pl.col("zero_for_one")
    in_range = (
        pl.when(flat)
        .then(
            (pl.col("tick_lower") <= pl.col("tick_start"))
            & (pl.col("tick_start") < pl.col("tick_upper"))
        )
        .otherwise((pa_ < hi) & (lo < pb_))
    )
    part = pl.when(zfo).then(usdc / usdc_step).otherwise(eth / eth_step)
    return j.filter(in_range).select(
        "seg",
        "block_number",
        "log_index",
        "step",
        "day",
        fee_usd=pl.col("fee_usd") * share * pl.when(whole).then(1.0).otherwise(part),
        lvr_0=pl.when(whole)
        .then(pl.col("lvr_0") * share)
        .when(zfo)
        .then(ell * (eth * p0 - usdc))
        .otherwise(ell * (usdc - eth * p0)),
        share=share,
    )


def held_from_flows(flows: pl.DataFrame, snapshot_block: int) -> pl.DataFrame:
    """Each position's stretches of constant liquidity > 0 inside the window (spec 5.2).

    Liquidity is the running sum of liquidity_delta in (block_number, pool_log_index) order from
    the start of history; a change at pool log (b, l) holds from (b, l + 1), so a step at that
    log still sees the old liquidity. A stretch open at the snapshot starts at the window's first
    block, before its first log."""
    first = snapshot_block + 1
    w = first * _K - 1
    return (
        flows.with_columns(pl.col("liquidity_delta").cast(pl.Int128))
        .filter(pl.col("liquidity_delta") != 0)
        .group_by("position_id", "block_number", "pool_log_index")
        .agg(pl.col("liquidity_delta").sum())
        .sort("position_id", "block_number", "pool_log_index")
        .with_columns(
            liquidity=pl.col("liquidity_delta").cum_sum().over("position_id"),
            start_block="block_number",
            start_log=pl.col("pool_log_index") + 1,
        )
        .with_columns(
            end_block=pl.col("start_block").shift(-1).over("position_id").fill_null(OPEN_BLOCK),
            end_log=pl.col("start_log").shift(-1).over("position_id").fill_null(0),
        )
        .filter((order_key("end_block", "end_log") > w) & (pl.col("liquidity") > 0))
        .with_columns(_pre=order_key("start_block", "start_log") < w)
        .select(
            "position_id",
            seg=pl.int_range(pl.len()).over("position_id"),
            start_block=pl.when("_pre").then(first).otherwise("start_block"),
            start_log=pl.when("_pre").then(-1).otherwise("start_log"),
            end_block="end_block",
            end_log="end_log",
            liquidity=pl.col("liquidity").cast(pl.Float64),
        )
    )
