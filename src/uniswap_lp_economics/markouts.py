"""Markouts against Binance (spec 5.2-5.3): per-swap columns and grouped tables.

Trader side, USD: markout(h) = -(amount_usdc + amount_eth * P_cex(t0 + h)), with pool amounts
(positive = into the pool) that already include the swap fee. Positive = the swap won.
Protocol fee: exact per-step cut from swap_fees (spec P2), valued at P_cex(t0).
"""

import math
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1, HORIZONS_S
from uniswap_lp_economics.flows import SIZE_BUCKETS
from uniswap_lp_economics.io import ordered_group_by

N_BOOT = 1000
SEED = 42
STALE_S = 5.0
GROUPINGS: dict[str, list[str]] = {
    "all": [],
    "flow_label": ["flow_label"],
    "size_bucket": ["size_bucket"],
    "flow_label_x_size": ["flow_label", "size_bucket"],
}


def add_markouts(df: pl.DataFrame, horizons: tuple[int, ...] = HORIZONS_S) -> pl.DataFrame:
    proto = pl.col("protocol_fee_raw").cast(pl.Float64)
    out = df.with_columns(
        protocol_fee_usd=pl.when(proto.is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .when(pl.col("fee_token") == "USDC")
        .then(proto / 10**DECIMALS0)
        .when(pl.col("fee_token") == "WETH")
        .then(proto / 10**DECIMALS1 * pl.col("p_cex_0"))
        .otherwise(0.0)
    )
    out = out.with_columns(
        (-(pl.col("amount_usdc") + pl.col("amount_eth") * pl.col(f"p_cex_{h}"))).alias(
            f"markout_usd_{h}"
        )
        for h in horizons
    )
    has_notional = pl.col("notional_usd") > 0
    return out.with_columns(
        *[
            pl.when(has_notional)
            .then(pl.col(f"markout_usd_{h}") / pl.col("notional_usd") * 1e4)
            .alias(f"markout_bp_{h}")
            for h in horizons
        ],
        *[
            (-pl.col(f"markout_usd_{h}") - pl.col("protocol_fee_usd")).alias(f"lp_markout_usd_{h}")
            for h in horizons
        ],
    )


def day_bootstrap_ci(
    daily_markout: NDArray[np.float64],
    daily_notional: NDArray[np.float64],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> tuple[float, float]:
    """95% interval of sum(markout) / sum(notional) in bp, resampling whole days."""
    n_days = len(daily_markout)
    if n_days == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_days, size=(n_boot, n_days))
    num = daily_markout[idx].sum(axis=1)
    den = daily_notional[idx].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        stat = np.where(den > 0, num / den * 1e4, np.nan)
    if np.isnan(stat).all():
        return math.nan, math.nan
    lo, hi = np.nanpercentile(stat, [2.5, 97.5])
    return float(lo), float(hi)


def _group_order(group_cols: list[str], key: tuple[Any, ...]) -> tuple[tuple[int, str], ...]:
    """Sort key: size buckets in bucket order (smallest first), other columns alphabetically."""
    return tuple(
        (SIZE_BUCKETS.index(v) if v in SIZE_BUCKETS else len(SIZE_BUCKETS), "")
        if col == "size_bucket"
        else (0, str(v))
        for col, v in zip(group_cols, key, strict=True)
    )


def markout_table(
    aligned: pl.DataFrame,
    group_cols: list[str],
    horizons: tuple[int, ...] = HORIZONS_S,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> pl.DataFrame:
    """Per group and horizon: swaps, notional, total markout, notional-weighted mean bp
    (= sum markout / sum notional), median bp and a 95% day-bootstrap interval.

    Swaps without a reference at a horizon are left out of that horizon only. Days come from
    the whole table, so a group's quiet days are resampled as zero-volume days.
    """
    base = aligned.with_columns(day=pl.col("block_timestamp").dt.date())
    days = base["day"].unique().sort().to_list()
    rows: list[dict[str, Any]] = []
    for h in horizons:
        m, bp = f"markout_usd_{h}", f"markout_bp_{h}"
        valid = base.filter(pl.col(m).is_not_null())
        if valid.height == 0:
            continue
        groups: dict[tuple[Any, ...], pl.DataFrame] = (
            valid.partition_by(group_cols, as_dict=True, maintain_order=True)
            if group_cols
            else {(): valid}
        )
        for key in sorted(groups, key=lambda k: _group_order(group_cols, k)):
            g = groups[key]
            daily = ordered_group_by(g, "day").agg(pl.col(m).sum(), pl.col("notional_usd").sum())
            by_day = {d: (mk, nt) for d, mk, nt in daily.iter_rows()}
            dm = np.array([by_day.get(d, (0.0, 0.0))[0] for d in days], dtype=np.float64)
            dn = np.array([by_day.get(d, (0.0, 0.0))[1] for d in days], dtype=np.float64)
            lo, hi = day_bootstrap_ci(dm, dn, n_boot, seed)
            notional = float(g["notional_usd"].sum())
            total = float(g[m].sum())
            median = g[bp].median()
            rows.append(
                {
                    **dict(zip(group_cols, key, strict=True)),
                    "horizon_s": h,
                    "swaps": g.height,
                    "notional_usd": notional,
                    "markout_usd": total,
                    "mean_bp": total / notional * 1e4 if notional > 0 else None,
                    "median_bp": None if median is None else float(median),  # type: ignore[arg-type]
                    "ci_lo_bp": lo,
                    "ci_hi_bp": hi,
                }
            )
    schema: dict[str, Any] = {
        **dict.fromkeys(group_cols, pl.String),
        "horizon_s": pl.Int64,
        "swaps": pl.Int64,
        "notional_usd": pl.Float64,
        "markout_usd": pl.Float64,
        "mean_bp": pl.Float64,
        "median_bp": pl.Float64,
        "ci_lo_bp": pl.Float64,
        "ci_hi_bp": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


def markout_tables(aligned: pl.DataFrame, horizons: tuple[int, ...] = HORIZONS_S) -> pl.DataFrame:
    frames = [
        markout_table(aligned, cols, horizons).with_columns(grouping=pl.lit(name))
        for name, cols in GROUPINGS.items()
    ]
    stacked = pl.concat(frames, how="diagonal")
    group_cols = list(dict.fromkeys(c for cols in GROUPINGS.values() for c in cols))
    return stacked.select("grouping", *group_cols, pl.exclude("grouping", *group_cols))


def exclude_stale(aligned: pl.DataFrame, max_age_s: float = STALE_S) -> pl.DataFrame:
    """Swaps whose time-zero reference trade is at most `max_age_s` old."""
    return aligned.filter(pl.col("cex_age_s_0") <= max_age_s)
