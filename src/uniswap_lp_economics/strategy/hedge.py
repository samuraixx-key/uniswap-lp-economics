"""The perpetual delta hedge (spec 8): a short of the position's WETH on a USDC-margined perp.

The hedge is the risk lever: it changes the spread of daily P&L, not fees - LVR. The position is
valued on the perp-minute grid from the block-start state in force at each minute; hedge P&L and
trade costs are booked at the perp close, so the perp-spot basis is in the hedge's P&L by
construction.
"""

import math

import polars as pl

from uniswap_lp_economics.config import HOUR_US
from uniswap_lp_economics.io import ordered_group_by
from uniswap_lp_economics.strategy.params import (
    HEDGE_DRIFT,
    HEDGE_RULES,
    TAKER_FEE_BP,
    TAKER_FEE_SENSITIVITY_BP,
)
from uniswap_lp_economics.strategy.ranges import _Q96, _per_unit

MINUTE_US = 60_000_000
DAY_US = 24 * 3600 * 1_000_000
SIM_COLUMNS = ["day", "hedge_pnl_usd", "funding_usd", "trade_usd", "rehedges"]


def _day(ts: str) -> pl.Expr:
    return pl.from_epoch(ts, "us").dt.date()


def position_path(segs: pl.DataFrame, starts: pl.DataFrame, minutes: pl.DataFrame) -> pl.DataFrame:
    """ts_us, eth, value_usd per minute: the position's WETH and its value at p_ref_0, from the
    last block-start state at or before the minute and the segment in force at that block.
    Minutes before the first state, or whose block is past the last segment, are left out."""
    state = (
        starts.select("block_number", "ts_us", "sqrt_price_x96", "p_ref_0")
        .sort("ts_us")
        .rename({"ts_us": "_state_us"})
    )
    seg = segs.sort("start_block").select(
        "start_block", "end_block", "tick_lower", "tick_upper", "liquidity"
    )
    usdc, eth = _per_unit(
        pl.col("sqrt_price_x96").cast(pl.Float64) / _Q96, pl.col("tick_lower"), pl.col("tick_upper")
    )
    ell = pl.col("liquidity")
    return (
        minutes.select("ts_us")
        .sort("ts_us")
        # a minute's close is at open + 60 s: the state in force then goes with the perp close
        .with_columns(_close_us=pl.col("ts_us") + MINUTE_US)
        .join_asof(state, left_on="_close_us", right_on="_state_us", strategy="backward")
        .drop_nulls("block_number")
        .set_sorted("block_number")
        .join_asof(seg, left_on="block_number", right_on="start_block", strategy="backward")
        .filter(pl.col("block_number") < pl.col("end_block"))
        .select("ts_us", eth=ell * eth, value_usd=ell * (usdc + eth * pl.col("p_ref_0")))
    )


def _hedge_series(df: pl.DataFrame, rule: str) -> tuple[list[float], list[bool]]:
    """h per minute, and whether the rule re-set it there (not the first set)."""
    if rule not in HEDGE_RULES:
        raise ValueError(f"unknown hedge rule {rule!r}")
    ts, eth, close, value = (df[c].to_list() for c in ("ts_us", "eth", "close", "value_usd"))
    h: list[float] = []
    fired: list[bool] = []
    for i, e in enumerate(eth):
        if rule == "never":
            go = False
        elif i == 0:
            go = True
        elif rule == "daily":
            go = ts[i] // DAY_US != ts[i - 1] // DAY_US
        elif rule == "hourly":
            go = ts[i] // HOUR_US != ts[i - 1] // HOUR_US
        else:  # drift
            go = abs(e - h[-1]) * close[i] > HEDGE_DRIFT * value[i]
        h.append(e if go else (h[-1] if h else 0.0))
        fired.append(go and i > 0)
    return h, fired


def simulate(
    path: pl.DataFrame, perp: pl.DataFrame, funding: pl.DataFrame, rule: str, taker_fee_bp: float
) -> pl.DataFrame:
    """Per day of the path's minutes: hedge P&L, funding, trade cost and re-hedge count.

    A minute's increments are booked on its day: hedge `-h_prev x d(close)`, trade
    `|dh| x close x fee`. A funding row applies to the hedge held while its minute runs (the
    previous re-set: this minute's trades at its close), valued at that minute's close
    (`+h x close x rate`); a row outside the minute grid is dropped."""
    df = path.sort("ts_us").join(perp, on="ts_us", how="left", maintain_order="left")
    if df["close"].is_null().any():
        raise ValueError("a path minute has no perp close")
    h, fired = _hedge_series(df, rule)
    df = df.with_columns(h=pl.Series(h, dtype=pl.Float64), fired=pl.Series(fired)).with_columns(
        h_prev=pl.col("h").shift(1).fill_null(0.0), dclose=pl.col("close").diff().fill_null(0.0)
    )
    per_day = (
        df.select(
            day=_day("ts_us"),
            hedge_pnl_usd=-pl.col("h_prev") * pl.col("dclose"),
            trade_usd=(pl.col("h") - pl.col("h_prev")).abs() * pl.col("close") * taker_fee_bp / 1e4,
            rehedges=pl.col("fired").cast(pl.Int64),
        )
        .pipe(ordered_group_by, "day")
        .agg(pl.all().sum())
    )
    paid = (
        funding.sort("ts_us")
        .join_asof(
            df.select("ts_us", h="h_prev", close="close").rename({"ts_us": "_minute_us"}),
            left_on="ts_us",
            right_on="_minute_us",
            strategy="backward",
        )
        .filter(pl.col("ts_us") - pl.col("_minute_us") < MINUTE_US)  # inside the minute's span
        .select(day=_day("_minute_us"), funding_usd=pl.col("h") * pl.col("close") * pl.col("rate"))
        .pipe(ordered_group_by, "day")
        .agg(pl.col("funding_usd").sum())
    )
    return (
        per_day.join(paid, on="day", how="left", maintain_order="left")
        .with_columns(pl.col("funding_usd").fill_null(0.0))
        .select(SIM_COLUMNS)
    )


def _stats(daily_usd: pl.Series, twv_total: float, capital: float) -> tuple[float, float, float]:
    """bp per day on the mean position value; sd and mean of the daily USD per $1M of capital."""
    scale = 1e6 / capital
    total, mean, sd = daily_usd.sum(), daily_usd.mean(), daily_usd.std()
    return (
        float(total) / twv_total * 1e4 if twv_total > 0 else math.nan,
        math.nan if sd is None else float(sd) * scale,  # type: ignore[arg-type]
        float(mean) * scale,  # type: ignore[arg-type]
    )


def hedge_table(
    lp_daily: pl.DataFrame,
    path: pl.DataFrame,
    perp: pl.DataFrame,
    funding: pl.DataFrame,
    capital: float,
) -> pl.DataFrame:
    """Daily USD P&L (position value change + fees - gas - trade + hedge) per hedge rule and
    taker fee, plus the hedge-free `rebalancing_benchmark` (fees - LVR - gas - trade).
    `funding_daily_usd_per_1m` is the mean daily funding the hedge received (positive = paid to it).

    The day grid is `lp_daily`'s; every per-day series is zero-filled on it, and the path must
    not reach outside it. `never` is the unhedged position, listed once with taker fee 0."""
    grid = lp_daily.select("day")
    dv = (
        path.sort("ts_us")
        .select(day=_day("ts_us"), dv=pl.col("value_usd").diff().fill_null(0.0))
        .pipe(ordered_group_by, "day")
        .agg(pl.col("dv").sum())
    )
    if missing := set(dv["day"]) - set(grid["day"]):
        raise ValueError(f"path minutes on days outside the day grid: {sorted(missing)}")
    lp = lp_daily.join(dv, on="day", how="left", maintain_order="left").fill_null(0.0)
    unhedged = lp["dv"] + lp["fee_usd"] - lp["gas_usd"] - lp["trade_usd"]
    twv = float(lp["twv_usd"].sum())
    cells = [("never", 0.0)] + [
        (r, f)
        for r in HEDGE_RULES
        if r != "never"
        for f in (TAKER_FEE_BP, *TAKER_FEE_SENSITIVITY_BP)
    ]
    rows: list[tuple[str, str, float | None, float, float, float, float]] = []
    for rule, fee in cells:
        sim = grid.join(
            simulate(path, perp, funding, rule, fee), on="day", how="left", maintain_order="left"
        ).fill_null(0.0)
        total = unhedged + sim["hedge_pnl_usd"] + sim["funding_usd"] - sim["trade_usd"]
        funding_mean = float(sim["funding_usd"].mean()) * 1e6 / capital  # type: ignore[arg-type]
        rows.append((f"hedge_{rule}", rule, fee, *_stats(total, twv, capital), funding_mean))
    bench = lp["fee_usd"] - lp["lvr_usd"] - lp["gas_usd"] - lp["trade_usd"]
    rows.append(("rebalancing_benchmark", "none", None, *_stats(bench, twv, capital), 0.0))
    return pl.DataFrame(
        rows,
        schema={
            "strategy": pl.String,
            "rule": pl.String,
            "taker_fee_bp": pl.Float64,
            "bp_per_day": pl.Float64,
            "sd_daily_usd_per_1m": pl.Float64,
            "mean_daily_usd_per_1m": pl.Float64,
            "funding_daily_usd_per_1m": pl.Float64,
        },
        orient="row",
    )
