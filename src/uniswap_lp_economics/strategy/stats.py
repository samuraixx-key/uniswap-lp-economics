"""Paired day bootstrap and the pre-registered verdicts (spec section 7), plus the break-even
arithmetic of spec 6.5. Pure functions; no I/O."""

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from uniswap_lp_economics.lp.theory import N_BOOT, SEED
from uniswap_lp_economics.strategy.params import (
    BASELINE_FEE_BP,
    DELTA_DIVISOR,
    UNDEFINED_MAX_SHARE,
)

PROTOCOL_CUTS = (0.0, 0.1, 0.25)
BELOW = "not tested (below baseline)"


def day_index(n_days: int, n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray:
    """The one draw matrix every cell shares; drawn exactly as theory.day_bootstrap_sum draws."""
    return np.random.default_rng(seed).integers(0, n_days, size=(n_boot, n_days))


def on_grid(daily: pl.DataFrame, days: list[date], cols: list[str]) -> pl.DataFrame:
    """Left-join a per-day frame onto the full day grid, zeros for missing days, so draws that
    index days stay paired across strategies."""
    if daily["day"].is_duplicated().any():
        raise ValueError("a per-day frame has a duplicate day: draws would not stay paired")
    grid = pl.DataFrame({"day": days}, schema={"day": pl.Date})
    return grid.join(
        daily.select("day", *cols), on="day", how="left", maintain_order="left"
    ).with_columns(pl.col(c).fill_null(0.0) for c in cols)


def ratio_draws(num: np.ndarray, den: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Per draw sum(num) / sum(den); nan where the summed denominator is not positive."""
    n = num[idx].sum(axis=1)
    d = den[idx].sum(axis=1)
    out: np.ndarray = np.divide(n, d, out=np.full(d.shape, np.nan), where=d > 0)
    return out


@dataclass(frozen=True)
class Paired:
    point: float
    lo: float
    hi: float
    n_undefined: int
    inside: bool
    above: bool
    below: bool


def paired(a: np.ndarray, b: np.ndarray, point: float, delta: float) -> Paired:
    """95% interval and the three pre-registered flags for the draws of a - b (spec 7, 7.1)."""
    d = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)  # nan if either is
    defined = d[~np.isnan(d)]
    n_undef = len(d) - len(defined)
    if len(defined) == 0:
        return Paired(point, math.nan, math.nan, n_undef, False, False, False)
    lo, hi = np.percentile(defined, [2.5, 97.5])
    # undefined draws sit at +inf: they count against "inside" and never toward above/below
    alo, ahi = np.percentile(np.where(np.isnan(d), np.inf, d), [2.5, 97.5], method="inverted_cdf")
    inside = n_undef / len(d) <= UNDEFINED_MAX_SHARE and bool(alo >= -delta and ahi <= delta)
    return Paired(point, float(lo), float(hi), n_undef, inside, bool(lo > delta), bool(hi < delta))


def delta_from(r0: float) -> float:
    if not math.isfinite(r0):
        raise ValueError(f"r0 = {r0} is not finite: the pre-registered margin is undefined")
    if r0 >= 1:
        raise ValueError(
            f"full range broke even in July (r0 = {r0}): the pre-registered margin is undefined"
        )
    return (1 - r0) / DELTA_DIVISOR


def range_verdict(cells: dict[str, Paired]) -> str:
    if not cells:
        raise ValueError("no counted cell: the range verdict is undefined")
    if any(c.above for c in cells.values()):
        return "fails"
    return "holds" if all(c.inside for c in cells.values()) else "inconclusive"


def fee_verdicts(
    levels: dict[float, Paired], calibrated: bool, baseline_bp: float = BASELINE_FEE_BP
) -> tuple[dict[float, str], str]:
    if not any(f > baseline_bp for f in levels):
        raise ValueError(f"no fee level above the baseline {baseline_bp:g} bp: nothing to test")
    per: dict[float, str] = {}
    for f, p in levels.items():
        if f == baseline_bp:
            continue
        if f < baseline_bp:
            per[f] = BELOW
        elif not calibrated:
            per[f] = "not tested (calibration failed)"
        else:
            per[f] = "holds" if p.above else "fails" if p.below else "inconclusive"
    if not calibrated:
        return per, "not tested (calibration failed)"
    holding = [f for f, v in per.items() if v == "holds"]
    return per, f"holds from {min(holding):g} bp" if holding else "fails"


def break_even_share(r_f: float, r_5: float, fees_kept_f: float, lvr_kept_f: float) -> float | None:
    den = fees_kept_f - lvr_kept_f
    return (r_f - r_5) / den if den > 0 else None


def interp(xs: list[float], ys: list[float], x: float) -> float:
    return float(np.interp(x, xs, ys))


def break_even_fee(fees_bp: list[float], ratios: list[float]) -> float | None:
    """Lowest fee where the ratio reaches 1, linear between grid points; None if never."""
    if ratios and ratios[0] >= 1:
        return fees_bp[0]
    for x0, y0, x1, y1 in zip(fees_bp, ratios, fees_bp[1:], ratios[1:], strict=False):
        if y1 >= 1:
            return x0 + (x1 - x0) * (1 - y0) / (y1 - y0)
    return None


def protocol_cut(fees_lp: float, cut: float) -> float:
    """LP fees at protocol cut `cut`, from LP fees measured at the actual 1/4 cut."""
    return fees_lp * (1 - cut) / (1 - 0.25)
