"""Theoretical LVR and volatility regimes (spec section 5).

Concentrated liquidity L at price p loses LVR at sigma^2 * L_dec * sqrt(p) / 4 per unit time
(full range: sigma^2/8 x pool value). Over each grid interval the realised r^2 of the Binance
price replaces sigma^2 dt. With fees and discrete blocks, arbitrage happens only in a fraction
P_trade = 1 / (1 + eta), eta = sqrt(2 lambda) gamma / sigma of blocks (Milionis, Moallemi,
Roughgarden 2023, arXiv:2305.14604, Theorem 1 and Eq. 12): expected arbitrage profit is about
LVR x P_trade and the fees it pays about LVR x (1 - P_trade).
"""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import polars as pl

from uniswap_lp_economics.align import reference_at
from uniswap_lp_economics.config import BLOCK_TIME_S, DAY_S, DECIMALS0, DECIMALS1, FEE_PIPS, US

GAMMA = math.log1p(FEE_PIPS / 1_000_000)
LAMBDA = 1 / BLOCK_TIME_S
L_DEC = 10.0 ** (-(DECIMALS0 + DECIMALS1) / 2)  # raw liquidity -> sqrt(USDC x WETH) units
REGIMES = ("low", "mid", "high")
N_BOOT = 1000
SEED = 42


def p_trade(sigma_per_sqrt_s: float, gamma: float = GAMMA, lam: float = LAMBDA) -> float:
    if sigma_per_sqrt_s <= 0:
        return 0.0
    return 1.0 / (1.0 + math.sqrt(2 * lam) * gamma / sigma_per_sqrt_s)


def price_grid(
    ref: pl.DataFrame, start_us: int, end_us: int, step_s: int, data_end_us: int
) -> pl.DataFrame:
    """The reference price as of every step in [start_us, end_us]."""
    times = pl.Series("ts_us", list(range(start_us, end_us + 1, step_s * US)), dtype=pl.Int64)
    p = reference_at(times, ref, data_end_us)["price"]
    return pl.DataFrame({"ts_us": times, "price": p})


def _day(col: str) -> pl.Expr:
    return pl.from_epoch(pl.col(col), time_unit="us").dt.date().alias("day")


def interval_theory(grid: pl.DataFrame, blocks_state: pl.DataFrame) -> pl.DataFrame:
    """Per grid interval: r^2 of the price and r^2 x L_dec x sqrt(p) / 4, with the active
    liquidity in force at the interval start: the end-of-block liquidity of the last block at or
    before it (the state the next block's arbitrage trades against)."""
    g = (
        grid.sort("ts_us")
        .with_columns(r=(pl.col("price").shift(-1) / pl.col("price")).log())
        .filter(pl.col("r").is_not_null() & pl.col("r").is_finite())
    )
    state = blocks_state.select(
        "ts_us", "block_number", liq=pl.col("end_liquidity").cast(pl.Float64)
    ).sort("ts_us")
    j = g.join_asof(state, on="ts_us", strategy="backward")
    return j.select(
        "ts_us",
        "block_number",
        r2=pl.col("r") ** 2,
        lvr_theory=pl.col("r") ** 2 * pl.col("liq") * L_DEC * pl.col("price").sqrt() / 4,
    )


def daily_theory(int_1s: pl.DataFrame, int_1m: pl.DataFrame) -> pl.DataFrame:
    one = int_1s.group_by(_day("ts_us")).agg(
        rv_1s=pl.col("r2").sum(), theory_1s=pl.col("lvr_theory").sum()
    )
    minute = int_1m.group_by(_day("ts_us")).agg(theory_1m=pl.col("lvr_theory").sum())
    d = one.join(minute, on="day", how="left").sort("day")
    pt = [p_trade(math.sqrt(rv / DAY_S)) for rv in d["rv_1s"].to_list()]
    return (
        d.with_columns(
            sigma_annual=(pl.col("rv_1s") * 365).sqrt(),
            p_trade=pl.Series(pt, dtype=pl.Float64),
        )
        .with_columns(
            theory_arb=pl.col("theory_1s") * pl.col("p_trade"),
            theory_arb_fees=pl.col("theory_1s") * (1 - pl.col("p_trade")),
        )
        .select(
            "day",
            "rv_1s",
            "sigma_annual",
            "theory_1s",
            "theory_1m",
            "p_trade",
            "theory_arb",
            "theory_arb_fees",
        )
    )


def measured_daily(steps: pl.DataFrame, aligned: pl.DataFrame) -> pl.DataFrame:
    """Daily fees and LVR over accrued steps (a step with no liquidity in range earns no one),
    as the headline totals count them; protocol fees from every swap."""
    searcher = pl.col("flow_label") == "searcher"
    m = (
        steps.filter(pl.col("accrued"))
        .group_by(_day("ts_us"))
        .agg(
            fees_usd=pl.col("fee_usd").sum(),
            lvr_0=pl.col("lvr_0").sum(),
            lvr_12=pl.col("lvr_12").sum(),
            lvr_0_searcher=pl.col("lvr_0").filter(searcher).sum(),
            fees_searcher=pl.col("fee_usd").filter(searcher).sum(),
        )
    )
    proto = aligned.group_by(day=pl.col("block_timestamp").dt.date()).agg(
        protocol_fee_usd=pl.col("protocol_fee_usd").sum(),
        protocol_fees_searcher=pl.col("protocol_fee_usd").filter(searcher).sum(),
    )
    return (
        m.join(proto, on="day", how="left")
        .with_columns(pl.col("protocol_fee_usd", "protocol_fees_searcher").fill_null(0.0))
        .sort("day")
        .select(
            "day",
            "fees_usd",
            "protocol_fee_usd",
            "lvr_0",
            "lvr_12",
            "lvr_0_searcher",
            "fees_searcher",
            "protocol_fees_searcher",
        )
    )


def regimes(daily: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Terciles of daily realised volatility (by rank), and per-regime totals."""
    n = daily.height
    rank = pl.col("sigma_annual").rank("ordinal")
    tagged = daily.with_columns(
        regime=pl.when(rank <= n / 3)
        .then(pl.lit("low"))
        .when(rank <= 2 * n / 3)
        .then(pl.lit("mid"))
        .otherwise(pl.lit("high"))
    )
    cols = [c for c in ("fees_usd", "lvr_0", "theory_1s", "theory_arb") if c in tagged.columns]
    summary = tagged.group_by("regime").agg(
        days=pl.len(),
        sigma_annual_mean=pl.col("sigma_annual").mean(),
        **{c: pl.col(c).sum() for c in cols},
    )
    if {"fees_usd", "lvr_0"} <= set(cols):
        summary = summary.with_columns(fees_minus_lvr_usd=pl.col("fees_usd") - pl.col("lvr_0"))
        if "protocol_fee_usd" in tagged.columns:  # swap fees before the protocol's cut
            proto = tagged.group_by("regime").agg(pl.col("protocol_fee_usd").sum())
            summary = summary.join(proto, on="regime").with_columns(
                total_fees_minus_lvr_usd=pl.col("fees_minus_lvr_usd") + pl.col("protocol_fee_usd")
            )
    order = pl.DataFrame({"regime": list(REGIMES), "_o": [0, 1, 2]})
    return tagged, summary.join(order, on="regime").sort("_o").drop("_o")


def regime_by_group(days: pl.DataFrame, groups: pl.DataFrame, daily: pl.DataFrame) -> pl.DataFrame:
    """Fees, LVR and fees - LVR per volatility regime and LP type, from per-day attribution."""
    return (
        days.join(groups, on="position_id", how="inner")
        .join(daily.select("day", "regime"), on="day", how="inner")
        .group_by("regime", "lp_type")
        .agg(fees_usd=pl.col("fee_usd").sum(), lvr_0_usd=pl.col("lvr_0").sum())
        .with_columns(fees_minus_lvr_usd=pl.col("fees_usd") - pl.col("lvr_0_usd"))
        .join(pl.DataFrame({"regime": list(REGIMES), "_o": [0, 1, 2]}), on="regime")
        .sort("_o", "lp_type")
        .drop("_o")
    )


def day_bootstrap_sum(
    values: Sequence[float], n_boot: int = N_BOOT, seed: int = SEED
) -> tuple[float, float]:
    """95% interval of a window total from a bootstrap over days (sub-project 2's day bootstrap,
    for a sum instead of a ratio): draw as many days as there are, with replacement, n_boot
    times, and take the 2.5th and 97.5th percentiles of the resampled sums."""
    v = np.asarray(values, dtype=np.float64)
    if len(v) == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    sums = v[rng.integers(0, len(v), size=(n_boot, len(v)))].sum(axis=1)
    lo, hi = np.percentile(sums, [2.5, 97.5])
    return float(lo), float(hi)


def daily_summary(daily: pl.DataFrame) -> dict[str, Any]:
    """Pool-level daily series (spec section 6): days on which LVR (0 s) exceeded LP fees, and
    total swap fees (LP + protocol), and day-bootstrap intervals for both fees - LVR totals."""
    lp = (daily["fees_usd"] - daily["lvr_0"]).to_list()
    total = (daily["fees_usd"] + daily["protocol_fee_usd"] - daily["lvr_0"]).to_list()
    out: dict[str, Any] = {
        "days": daily.height,
        "days_lvr_above_lp_fees": sum(x < 0 for x in lp),
        "days_lvr_above_total_fees": sum(x < 0 for x in total),
        "total_fees_usd": float((daily["fees_usd"] + daily["protocol_fee_usd"]).sum()),
        "fees_minus_lvr_usd": float(sum(lp)),
        "total_fees_minus_lvr_usd": float(sum(total)),
        "bootstrap": f"95%, {N_BOOT} resamples of days, seed {SEED}",
    }
    for key, values in (("fees_minus_lvr", lp), ("total_fees_minus_lvr", total)):
        out[f"{key}_ci_lo_usd"], out[f"{key}_ci_hi_usd"] = day_bootstrap_sum(values)
    return out
