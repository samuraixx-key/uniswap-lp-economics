"""Price discovery (spec 6): per-block pool vs Binance series, basis, gap episodes, lead-lag
and available-vs-captured arbitrage."""

import math
from typing import Any

import numpy as np
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


QUANTILES = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
MAX_LAG = 5
_DEFAULT_BLOCK_S = 12.0
EPISODE_SCHEMA: dict[str, Any] = {
    "start_block": pl.Int64,
    "end_block": pl.Int64,
    "n_blocks": pl.Int64,
    "start_ts_us": pl.Int64,
    "duration_s": pl.Float64,
    "peak_abs_bp": pl.Float64,
    "gap_weight": pl.Float64,
    "closer": pl.String,
}


def basis_stats(series: pl.DataFrame, band_bp: float = FEE_BAND_BP) -> dict[str, Any]:
    b = series["basis_bp"].drop_nulls().drop_nans()
    if b.len() == 0:
        return {"blocks": 0, "band_bp": band_bp}
    a = b.abs()
    return {
        "blocks": b.len(),
        "band_bp": band_bp,
        "mean_bp": float(b.mean()),  # type: ignore[arg-type]
        "quantiles_bp": {str(q): float(b.quantile(q)) for q in QUANTILES},  # type: ignore[arg-type]
        "abs_quantiles_bp": {str(q): float(a.quantile(q)) for q in QUANTILES},  # type: ignore[arg-type]
        "share_outside_band": float((a > band_bp).mean()),  # type: ignore[arg-type]
    }


def _closers(series: pl.DataFrame, swaps: pl.DataFrame) -> pl.DataFrame:
    """Per block: flow label of the swap that moved the pool's log price furthest toward Binance."""
    toward = (pl.col("pre_price_usd") / pl.col("p_cex")).log().abs() - (
        pl.col("price_usd") / pl.col("p_cex")
    ).log().abs()
    return (
        swaps.select("block_number", "log_index", "flow_label", "pre_price_usd", "price_usd")
        .join(series.select("block_number", "p_cex"), on="block_number", how="inner")
        .with_columns(toward=toward)
        .filter(pl.col("toward") > 0)
        .sort(["block_number", "toward", "log_index"], descending=[False, True, False])
        .group_by("block_number", maintain_order=True)
        .agg(closer=pl.col("flow_label").first())
    )


def find_episodes(series: pl.DataFrame, swaps: pl.DataFrame, k: float) -> pl.DataFrame:
    """Maximal runs of consecutive blocks with |basis_bp| > k (spec 6.3).

    The episode's last block e is the last one starting outside the band. Its closer is the
    flow label of the swap in e that moved the price furthest toward Binance, "cex" if no swap in
    e did, and "open" if e is the series' last block.
    """
    s = series.sort("block_number").with_columns(
        outside=(pl.col("basis_bp").abs() > k).fill_null(False),
        block_s=((pl.col("ts_us").shift(-1) - pl.col("ts_us")) / 1e6).fill_null(_DEFAULT_BLOCK_S),
    )
    if s.height == 0 or not s["outside"].any():
        return pl.DataFrame(schema=EPISODE_SCHEMA)
    last_block = int(s["block_number"].max())  # type: ignore[arg-type]
    s = s.with_columns(
        run=(pl.col("outside") != pl.col("outside").shift(1)).fill_null(True).cum_sum()
    )
    eps = (
        s.filter("outside")
        .group_by("run", maintain_order=True)
        .agg(
            start_block=pl.col("block_number").first(),
            end_block=pl.col("block_number").last(),
            n_blocks=pl.len().cast(pl.Int64),
            start_ts_us=pl.col("ts_us").first(),
            end_ts_us=pl.col("ts_us").last(),
            end_block_s=pl.col("block_s").last(),
            peak_abs_bp=pl.col("basis_bp").abs().max(),
            gap_weight=(pl.col("basis_bp").abs() * pl.col("block_s")).sum(),
        )
        .join(_closers(series, swaps), left_on="end_block", right_on="block_number", how="left")
    )
    return eps.select(
        "start_block",
        "end_block",
        "n_blocks",
        "start_ts_us",
        duration_s=(pl.col("end_ts_us") - pl.col("start_ts_us")) / 1e6 + pl.col("end_block_s"),
        peak_abs_bp="peak_abs_bp",
        gap_weight="gap_weight",
        closer=pl.when(pl.col("end_block") == last_block)
        .then(pl.lit("open"))
        .otherwise(pl.coalesce("closer", pl.lit("cex"))),
    ).sort("start_block")


def episode_summary(episodes: pl.DataFrame) -> pl.DataFrame:
    n = max(episodes.height, 1)
    weight = float(episodes["gap_weight"].sum()) or 1.0
    return (
        episodes.group_by("closer")
        .agg(
            episodes=pl.len().cast(pl.Int64),
            gap_weight=pl.col("gap_weight").sum(),
            median_duration_s=pl.col("duration_s").median(),
        )
        .with_columns(
            share_episodes=pl.col("episodes") / n,
            share_gap_weight=pl.col("gap_weight") / weight,
        )
        .select(
            "closer",
            "episodes",
            "share_episodes",
            "gap_weight",
            "share_gap_weight",
            "median_duration_s",
        )
        .sort(["episodes", "closer"], descending=[True, False])
    )


def cross_correlation(series: pl.DataFrame, max_lag: int = MAX_LAG) -> pl.DataFrame:
    """corr(pool_ret[b], cex_ret[b - lag]) for lag in [-max_lag, max_lag] (spec 6.4).

    Returns are per block, from one block's start to the next. A positive lag means Binance
    moved first and the pool followed `lag` blocks later.
    """
    s = series.sort("block_number")
    pool = np.diff(np.log(s["pool_price"].cast(pl.Float64).fill_null(np.nan).to_numpy()))
    cex = np.diff(np.log(s["p_cex"].cast(pl.Float64).fill_null(np.nan).to_numpy()))
    n = len(pool)
    rows: list[dict[str, Any]] = []
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = pool[lag:], cex[: n - lag]
        else:
            x, y = pool[:lag], cex[-lag:]
        mask = np.isfinite(x) & np.isfinite(y)
        corr = math.nan
        if mask.sum() > 2 and np.std(x[mask]) > 0 and np.std(y[mask]) > 0:
            corr = float(np.corrcoef(x[mask], y[mask])[0, 1])
        rows.append({"lag_blocks": lag, "corr": corr, "n": int(mask.sum())})
    return pl.DataFrame(rows, schema={"lag_blocks": pl.Int64, "corr": pl.Float64, "n": pl.Int64})


def ar1_half_life(series: pl.DataFrame) -> dict[str, float | None]:
    """OLS fit basis[b+1] = intercept + phi * basis[b]; half-life = ln(0.5) / ln(phi)."""
    s = series.sort("block_number")
    b = s["basis_bp"].cast(pl.Float64).fill_null(np.nan).to_numpy()
    x, y = b[:-1], b[1:]
    mask = np.isfinite(x) & np.isfinite(y)
    block_s = float(np.median(np.diff(s["ts_us"].to_numpy()))) / 1e6 if s.height > 1 else None
    if mask.sum() < 3 or np.ptp(x[mask]) == 0:  # too short, or no spread to regress on
        return {
            "phi": None,
            "intercept": None,
            "half_life_blocks": None,
            "median_block_s": block_s,
            "half_life_s": None,
        }
    phi, intercept = np.polyfit(x[mask], y[mask], 1)
    half_life = math.log(0.5) / math.log(phi) if 0 < phi < 1 else None
    return {
        "phi": float(phi),
        "intercept": float(intercept),
        "half_life_blocks": half_life,
        "median_block_s": block_s,
        "half_life_s": half_life * block_s if half_life is not None and block_s else None,
    }


def available_vs_captured(series: pl.DataFrame, aligned: pl.DataFrame) -> pl.DataFrame:
    """Daily available arbitrage (block starts) vs searchers' captured 0s markouts."""
    day = pl.col("block_timestamp").dt.date().alias("day")
    available = series.group_by(day).agg(
        available_usd=pl.col("available_usd").sum(),
        available_cex1bp_usd=pl.col("available_usd_cex1bp").sum(),
    )
    captured = (
        aligned.filter(pl.col("flow_label") == "searcher")
        .group_by(day)
        .agg(captured_usd=pl.col("markout_usd_0").sum())
    )
    return (
        available.join(captured, on="day", how="left")
        .with_columns(pl.col("captured_usd").fill_null(0.0))
        .sort("day")
    )


BASIS_HIST_RANGE_BP = 50.0
BASIS_HIST_BINS = 200


def basis_histogram(series: pl.DataFrame) -> pl.DataFrame:
    """Counts of the block-start basis in 0.5 bp bins over [-50, 50] bp, for figure 3. Values
    outside the range are clipped into the edge bins; null and NaN are dropped."""
    b = (
        series["basis_bp"]
        .drop_nulls()
        .drop_nans()
        .clip(-BASIS_HIST_RANGE_BP, BASIS_HIST_RANGE_BP)
        .to_numpy()
    )
    edges = np.linspace(-BASIS_HIST_RANGE_BP, BASIS_HIST_RANGE_BP, BASIS_HIST_BINS + 1)
    counts, _ = np.histogram(b, bins=edges)
    return pl.DataFrame(
        {"bin_lo_bp": edges[:-1], "bin_hi_bp": edges[1:], "blocks": counts.astype(np.int64)}
    )
