"""Reference and timing robustness (sub-project 4 spec sections 5.1-5.4).

LP fees - LVR under another reference price P or another t0 offset, through the L6 identity per
swap: fees - LVR = amount_usdc + amount_eth x P - protocol fee in USD. Each cell is the headline
plus the shift X(P_cell) - X(p_cex_0), summed by day, so the primary 0 s cell is the headline by
construction (flash-loan fees included). One set of resampled days serves every cell, so shifts
between cells get paired intervals.
"""

import numpy as np
import polars as pl

from uniswap_lp_economics.align import reference_at
from uniswap_lp_economics.config import US
from uniswap_lp_economics.lp.theory import N_BOOT, SEED

OFFSETS_S: tuple[float, ...] = tuple(x / 2 for x in range(-10, 9))
REFERENCES: tuple[str, ...] = (
    "binance_last_trade",  # the primary
    "binance_trade_side_mid",
    "binance_ethusdt_1s_close",
)
REFERENCE_LABELS: dict[str, str] = {
    "binance_last_trade": "Binance last trade",
    "binance_trade_side_mid": "Binance trade-side mid",
    "binance_ethusdt_1s_close": "Binance ETHUSDT 1 s",
}


def daily_shifts(
    swaps: pl.DataFrame,
    refs: dict[str, pl.DataFrame],
    end_us: int,
    offsets: tuple[float, ...] = OFFSETS_S,
) -> pl.DataFrame:
    """Per reference, offset and day: the shift of fees - LVR and of LP fees from the primary at
    0 s, and the swaps with no price (zero shift). Only WETH amounts move with the price."""
    weth = pl.col("fee_token") == "WETH"
    base = swaps.select(
        day=pl.col("block_timestamp").dt.date(),
        t0_us="t0_us",
        eth_kept=pl.col("amount_eth")
        - pl.when(weth).then(pl.col("protocol_fee_raw").cast(pl.Float64) / 1e18).otherwise(0.0),
        lp_eth=pl.when(weth).then(pl.col("lp_fee_raw").cast(pl.Float64) / 1e18).otherwise(0.0),
        p0="p_cex_0",
    )
    out = []
    for name in REFERENCES:
        for d in offsets:
            price = reference_at(base["t0_us"] + int(round(d * US)), refs[name], end_us)["price"]
            dp = base.with_columns(dp=price - pl.col("p0"))
            out.append(
                dp.group_by("day")
                .agg(
                    d_fees_minus_lvr_usd=(pl.col("eth_kept") * pl.col("dp")).fill_null(0.0).sum(),
                    d_lp_fees_usd=(pl.col("lp_eth") * pl.col("dp")).fill_null(0.0).sum(),
                    n_unpriced=pl.col("dp").is_null().sum().cast(pl.Int64),
                )
                .with_columns(reference=pl.lit(name), offset_s=pl.lit(float(d)))
            )
    return pl.concat(out).select(
        "reference", "offset_s", "day", "d_fees_minus_lvr_usd", "d_lp_fees_usd", "n_unpriced"
    )


def robustness_table(
    daily: pl.DataFrame, shifts: pl.DataFrame, n_boot: int = N_BOOT, seed: int = SEED
) -> pl.DataFrame:
    """One row per reference and offset: totals, the 95% day-bootstrap interval of fees - LVR,
    and its shift from the primary 0 s cell with a paired interval (the same days resampled).
    `daily` is lvr_daily's frame (day, fees_usd, lvr_0); a day missing from either side is 0."""
    days = sorted(set(daily["day"].to_list()) | set(shifts["day"].to_list()))
    grid = pl.DataFrame({"day": days}, schema={"day": pl.Date})
    base = grid.join(daily.select("day", "fees_usd", "lvr_0"), on="day", how="left").fill_null(0.0)
    headline = (base["fees_usd"] - base["lvr_0"]).to_numpy()
    # Drawn as theory.day_bootstrap_sum draws, so the primary 0 s interval is the headline's.
    idx = np.random.default_rng(seed).integers(0, len(days), size=(n_boot, len(days)))

    def vectors(reference: str, offset: float) -> tuple[np.ndarray, float, int]:
        s = shifts.filter((pl.col("reference") == reference) & (pl.col("offset_s") == offset))
        s = grid.join(s, on="day", how="left").fill_null(0)
        return (
            headline + s["d_fees_minus_lvr_usd"].to_numpy(),
            float(s["d_lp_fees_usd"].sum()),
            int(s["n_unpriced"].sum()),
        )

    offsets = sorted(set(shifts["offset_s"].to_list()))
    if 0.0 not in offsets:
        raise ValueError("the offsets must include 0 s, the primary cell")
    primary, _, _ = vectors(REFERENCES[0], 0.0)
    lp_fees = float(base["fees_usd"].sum())
    rows = []
    for reference in REFERENCES:
        for offset in offsets:
            v, d_lp, unpriced = vectors(reference, offset)
            lo, hi = np.percentile(v[idx].sum(axis=1), [2.5, 97.5])
            slo, shi = np.percentile((v - primary)[idx].sum(axis=1), [2.5, 97.5])
            fml = float(v.sum())
            rows.append(
                {
                    "reference": reference,
                    "offset_s": offset,
                    "lp_fees_usd": lp_fees + d_lp,
                    "lvr_usd": lp_fees + d_lp - fml,
                    "fees_minus_lvr_usd": fml,
                    "ci_lo_usd": float(lo),
                    "ci_hi_usd": float(hi),
                    "shift_usd": float((v - primary).sum()),
                    "shift_ci_lo_usd": float(slo),
                    "shift_ci_hi_usd": float(shi),
                    "n_unpriced": unpriced,
                }
            )
    return pl.DataFrame(rows)


def crossing_offset(offsets: list[float], values: list[float]) -> float | None:
    """The offset where the curve last goes from >= 0 to < 0, interpolated linearly between grid
    points; None when it never does."""
    found = None
    points = list(zip(offsets, values, strict=True))
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if y0 >= 0 > y1:
            found = x0 + (x1 - x0) * y0 / (y0 - y1)
    return found
