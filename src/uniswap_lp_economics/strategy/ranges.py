"""A price-taker position's share of recorded swap steps (spec 5.1), and range strategies scored
on it: rebalancing rules, gas and re-centring trade costs, peak share (spec 5.3-5.4).

Within a step, liquidity is constant and amounts between two sqrt prices follow the V3 delta
formulas, so a range whose bounds fall inside a step takes the part of the step between them.
"""

import math
from dataclasses import dataclass
from datetime import date

import polars as pl

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1, NPM_ADDRESS
from uniswap_lp_economics.strategy.params import FULL_RANGE, RULES
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick

_K = 2**20  # (block, log) order key = block * _K + log; a block's logs stay far below 2**20
OPEN_BLOCK = 2**40  # end block of a stretch still held when the history ends
_Q96 = float(2**96)
_CLAMP = 2**127 - 1  # Int128 max


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
    # Bounds of wide ranges pass Int128; clamped above every step price, they compare the same.
    top = steps.select(pl.max_horizontal(pl.col("sqrt_start").max(), pl.col("sqrt_end").max()))
    if top.height and (top.item() or 0) >= _CLAMP:
        raise ValueError("a step's sqrt price reaches the range-bound clamp")
    pa = [min(get_sqrt_ratio_at_tick(t), _CLAMP) for t in held["tick_lower"].to_list()]
    pb = [min(get_sqrt_ratio_at_tick(t), _CLAMP) for t in held["tick_upper"].to_list()]
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


FULL_TICK = 887_270  # the widest ticks on the pool's 10-tick spacing
_SPACING = 10
SEG_SCHEMA = {
    c: pl.Int64
    for c in ("seg", "start_block", "end_block", "center_tick", "tick_lower", "tick_upper")
}
STRATEGY_COLUMNS: tuple[str, ...] = (
    "strategy",
    "rule",
    "half_width_bp",
    "capital",
    "fees_over_lvr",
    "bp_per_day",
    "recentres",
    "gas_usd",
    "trade_usd",
    "in_range_share",
    "days_in_range",
    "peak_share",
    "flagged",
    "counted",
)
DAILY_COLUMNS = (
    "day",
    "fee_usd",
    "lvr_usd",
    "gas_usd",
    "trade_usd",
    "twv_usd",
    "in_range_blocks",
    "n_blocks",
    "recentres",
)


@dataclass
class LpCosts:
    """Window medians: gas of NFT position-manager mints and burn + collects, priority fee."""

    gas_mint: int
    gas_burn_collect: int
    priority_wei: int


@dataclass
class StrategyResult:
    daily: pl.DataFrame  # DAILY_COLUMNS, one row per day of the period, zeros where nothing
    peak_ratio: float  # max over attributed steps of the position's liquidity / pool liquidity
    segs: pl.DataFrame  # SEG_SCHEMA plus liquidity and eth_start (WETH at the segment start)
    bp_per_day: float


def range_ticks(center_tick: int, half_width_bp: int | None) -> tuple[int, int]:
    """A range of +-half_width ticks (one tick ~ 1 bp) around the centre, rounded outward to the
    tick spacing; None is full range."""
    if half_width_bp is None:
        return -FULL_TICK, FULL_TICK
    lo = (center_tick - half_width_bp) // _SPACING * _SPACING
    hi = -(-(center_tick + half_width_bp) // _SPACING) * _SPACING
    if hi == lo:
        hi += _SPACING
    return max(lo, -FULL_TICK), min(hi, FULL_TICK)


def segments(
    rule: str, half_width_bp: int | None, starts: pl.DataFrame, start_block: int, end_block: int
) -> pl.DataFrame:
    """The strategy's ranges over blocks [start_block, end_block] (spec 5.3), decided on each
    block-start tick of `starts`. A segment holds from its start block up to the next one's; the
    last ends at end_block + 1. Full range (half_width_bp None) and static never re-centre."""
    if rule not in RULES and rule != FULL_RANGE:
        raise ValueError(f"unknown rebalancing rule {rule!r}")
    rows = (
        starts.filter(pl.col("block_number").is_between(start_block, end_block))
        .sort("block_number")
        .select("block_number", "day", "tick")
        .rows()
    )
    if not rows or rows[0][0] != start_block:
        raise ValueError(f"no block-start state at the period's first block {start_block}")
    w = half_width_bp
    segs: list[list[int]] = []
    prev_day = rows[0][1]
    for b, day, tick in rows:
        if not segs:
            move = True
        else:
            c, lo, hi = segs[-1][3:6]
            move = w is not None and (
                (rule == "out_of_range" and (tick < lo or tick >= hi))
                or (rule == "band" and abs(tick - c) > w / 2)
                or (rule == "daily" and day != prev_day)
            )
        prev_day = day
        if move:
            segs.append([len(segs), b, 0, tick, *range_ticks(tick, w)])
    for s, nxt in zip(segs, segs[1:] + [[0, end_block + 1]], strict=True):
        s[2] = nxt[1]
    return pl.DataFrame(segs, schema=SEG_SCHEMA, orient="row")


def lp_costs(events: pl.DataFrame, blocks: pl.DataFrame) -> LpCosts:
    """Medians over the window's distinct transactions (spec 5.3): gas of those holding an NFT
    position-manager pool mint and no burn, gas of those holding a position-manager burn and a
    collect, and the priority fee (effective gas price - base fee) over both kinds."""
    ev, npm = pl.col("event"), pl.col("owner") == NPM_ADDRESS
    tx = events.group_by("tx_hash").agg(
        mint=((ev == "mint") & npm).any(),
        burn=(ev == "burn").any(),
        npm_burn=((ev == "burn") & npm).any(),
        collect=(ev == "collect").any(),
        gas=pl.col("receipt_gas_used").first(),
        price=pl.col("receipt_effective_gas_price").first(),
        block_number=pl.col("block_number").first(),
    )
    mints = tx.filter(pl.col("mint") & ~pl.col("burn"))
    burns = tx.filter(pl.col("npm_burn") & pl.col("collect"))
    both = pl.concat([mints, burns]).join(
        blocks.select("block_number", base=pl.col("base_fee_per_gas").cast(pl.Int64)),
        on="block_number",
        how="left",
    )
    if both["base"].is_null().any():
        raise ValueError("an LP transaction's block has no base fee")

    def median(frame: pl.DataFrame, expr: pl.Expr, what: str) -> int:
        m = frame.select(expr.median()).item()
        if m is None:
            raise ValueError(f"no {what} in the window")
        return int(round(m))

    return LpCosts(
        gas_mint=median(mints, pl.col("gas"), "position-manager mint transactions"),
        gas_burn_collect=median(burns, pl.col("gas"), "position-manager burn + collect"),
        priority_wei=median(both, pl.col("price") - pl.col("base"), "LP transactions"),
    )


def _per_unit(sqrt: pl.Expr, lo: pl.Expr, hi: pl.Expr) -> tuple[pl.Expr, pl.Expr]:
    """(USDC, WETH) per unit of liquidity at `sqrt` (sqrtPrice / 2^96), as
    pnl.time_weighted_value values a position."""
    sa, sb = pl.lit(1.0001).pow(lo / 2), pl.lit(1.0001).pow(hi / 2)
    sp = sqrt.clip(sa, sb)
    return (1 / sp - 1 / sb) / 10**DECIMALS0, (sp - sa) / 10**DECIMALS1


def score(
    steps: pl.DataFrame,
    segs: pl.DataFrame,
    starts: pl.DataFrame,
    grid: pl.DataFrame,
    capital: float,
    costs: LpCosts,
    taker_fee_bp: float,
    days: list[date],
) -> StrategyResult:
    """Score a strategy's segments on recorded steps as a price taker (spec 5.3).

    `capital` buys the first range at the first segment's block start (valued at the pool price
    and p_ref_0); each re-centring moves the old position's value at that block start into the
    new range, paying gas (burn + collect and mint at base fee + priority) and the taker fee on
    the WETH traded, both from cash, as fees are. `starts` also needs base_fee_wei. `grid` is the
    period's hourly ts_us, sqrt, p_cex; twv_usd is the mean of a day's hourly position values."""
    s = segs.sort("seg").join(
        starts.select("block_number", "ts_us", "day", "sqrt_price_x96", "p_ref_0", "base_fee_wei"),
        left_on="start_block",
        right_on="block_number",
        how="left",
    )
    need = pl.col("ts_us", "sqrt_price_x96", "p_ref_0", "base_fee_wei")
    if s.select(pl.any_horizontal(need.is_null()).any()).item():
        raise ValueError("a segment starts at a block with no state, reference price or base fee")
    sqrt, p = pl.col("sqrt_price_x96").cast(pl.Float64) / _Q96, pl.col("p_ref_0")
    lo, hi = pl.col("tick_lower"), pl.col("tick_upper")
    usdc_new, eth_new = _per_unit(sqrt, lo, hi)
    usdc_old, eth_old = _per_unit(sqrt, lo.shift(1), hi.shift(1))  # the previous range, here
    ell = pl.col("liquidity")
    gas_units = costs.gas_burn_collect + costs.gas_mint
    gas_price = pl.col("base_fee_wei").cast(pl.Float64) + costs.priority_wei
    s = (
        s.with_columns(
            _v_old=(usdc_old + eth_old * p).fill_null(capital),  # the first range buys `capital`
            _v_new=usdc_new + eth_new * p,
            _e_old=eth_old,
            _e_new=eth_new,
        )
        .with_columns(liquidity=(pl.col("_v_old") / pl.col("_v_new")).cum_prod())
        .with_columns(eth_start=ell * pl.col("_e_new"), _eth_before=ell.shift(1) * pl.col("_e_old"))
        .with_columns(
            trade_usd=(pl.col("eth_start") - pl.col("_eth_before")).abs() * p * taker_fee_bp / 1e4,
            gas_usd=pl.when(pl.col("seg") > 0).then(gas_units * gas_price / 1e18 * p),
        )
    )
    held = s.select(
        "seg",
        "start_block",
        "end_block",
        "tick_lower",
        "tick_upper",
        "liquidity",
        start_log=pl.lit(-2),  # a re-centring happens at block start, before the arbitrage (-1)
        end_log=pl.lit(-2),
    )
    att = attribute(steps, held)
    fees = att.group_by("day").agg(fee_usd=pl.col("fee_usd").sum(), lvr_usd=pl.col("lvr_0").sum())
    paid = (
        s.filter(pl.col("seg") > 0)
        .group_by("day")
        .agg(pl.col("gas_usd").sum(), pl.col("trade_usd").sum(), recentres=pl.len())
    )
    ranges = s.select("ts_us", "start_block", "tick_lower", "tick_upper", "liquidity")
    u, e = _per_unit(pl.col("sqrt"), lo, hi)
    twv = (
        grid.sort("ts_us")
        .join_asof(ranges.drop("start_block"), on="ts_us", strategy="backward")
        # an hour before the first block start is held by the first range
        .with_columns(
            pl.col("tick_lower", "tick_upper", "liquidity").fill_null(strategy="backward")
        )
        .group_by(day=pl.from_epoch("ts_us", "us").dt.date())
        .agg(twv_usd=(ell * (u + e * pl.col("p_cex"))).mean())
    )
    first, end = s["start_block"][0], s["end_block"][-1]
    blocks = (
        starts.filter((pl.col("block_number") >= first) & (pl.col("block_number") < end))
        .sort("block_number")
        .join_asof(ranges.drop("ts_us"), left_on="block_number", right_on="start_block")
        .group_by("day")
        .agg(
            in_range_blocks=((lo <= pl.col("tick")) & (pl.col("tick") < hi)).sum(),
            n_blocks=pl.len(),
        )
    )
    if missing := set(blocks["day"]) - set(days):
        raise ValueError(f"period blocks on days outside the day grid: {sorted(missing)}")
    daily = pl.DataFrame({"day": days}, schema={"day": pl.Date})
    for frame in (fees, paid, twv, blocks):
        daily = daily.join(frame, on="day", how="left")
    daily = daily.fill_null(0).select(
        *DAILY_COLUMNS[:6], *(pl.col(c).cast(pl.Int64) for c in DAILY_COLUMNS[6:])
    )
    fee, lvr, gas, trade, value = daily.select(pl.sum(*DAILY_COLUMNS[1:6])).row(0)
    peak = att["share"].max()
    return StrategyResult(
        daily=daily,
        peak_ratio=0.0 if peak is None else float(peak),  # type: ignore[arg-type]
        segs=s.select(*SEG_SCHEMA, "liquidity", "eth_start"),
        bp_per_day=(fee - lvr - gas - trade) / value * 1e4 if value > 0 else math.nan,
    )


def peak_share(peak_ratio: float, scale: float = 1.0) -> float:
    """The position's share of active liquidity, ell / (L + ell), at `scale` times its size."""
    r = peak_ratio * scale
    return r / (1 + r)
