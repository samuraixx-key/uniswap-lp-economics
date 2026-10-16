"""Chapter 'Does the pool follow Binance?' (figure 3): basis distribution, how long gaps last,
and lead-lag, from sub-project 2's results."""

import numpy as np
import polars as pl
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, FuncFormatter, MaxNLocator, NullFormatter

from uniswap_lp_economics.discovery import (
    BASIS_HIST_RANGE_BP,
    EPISODE_THRESHOLDS_BP,
    FEE_BAND_BP,
)
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import frame, new_figure, no_data, pal, panel_header, pct

DURATION_TICKS_S = (12, 24, 60, 300, 1800)


def _duration(v: float) -> str:
    return f"{v / 60:.0f} min" if v >= 60 else f"{v:.0f} s"


def pool_follows_binance(r: Results) -> Figure:
    p = pal()
    fig, (a, b, c) = new_figure(1, 3, top=0.74, bottom=0.17, wspace=0.43)
    # (a) basis distribution
    h = r.basis_hist
    mid = ((h["bin_lo_bp"] + h["bin_hi_bp"]) / 2).to_numpy()
    width = (h["bin_hi_bp"] - h["bin_lo_bp"]).to_numpy()
    n = h["blocks"].to_numpy().astype(float)
    total = n.sum()
    inside = float(n[np.abs(mid) < FEE_BAND_BP].sum() / total) if total else float("nan")
    a.axvspan(-FEE_BAND_BP, FEE_BAND_BP, color=p.fees, alpha=0.12, lw=0)
    if total:
        a.bar(mid, n / total * 100, width=width, color=p.other, lw=0)
        a.set_ylim(0, float((n / total * 100).max()) * 1.35)  # room for the band label
    else:
        no_data(a)
    a.set_xlim(-25, 25)
    panel_header(a, 1, "Distance between venues", "Pool vs Binance price at each block's start")
    a.set_xlabel("Pool vs Binance (bp at block start)")
    a.set_ylabel("% of blocks")
    a.text(
        0.03,
        0.97,
        f"{pct(inside)} of blocks inside\nthe ±{FEE_BAND_BP:g} bp fee band",
        transform=a.transAxes,
        ha="left",
        va="top",
        color=p.fees,
        fontsize=9.5,
    )
    # (b) survival of gap episodes at the primary threshold
    k = EPISODE_THRESHOLDS_BP[0]
    d = np.sort(
        r.episodes.filter(pl.col("threshold_bp") == k)["duration_s"]
        .drop_nulls()
        .to_numpy()
        .astype(float)
    )
    median = float(np.median(d)) if len(d) else float("nan")
    if len(d):
        share = 1.0 - np.arange(len(d)) / len(d)
        b.step(d, share, where="post", color=p.lvr, lw=2.2)
        b.set_xscale("log")
        ticks: list[float] = [float(t) for t in DURATION_TICKS_S if d[0] <= t <= d[-1]] or [
            float(d[0])
        ]
        b.xaxis.set_major_locator(FixedLocator(ticks))
        b.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _duration(v)))
        b.xaxis.set_minor_formatter(NullFormatter())
        b.axvline(median, color=p.muted, lw=1, ls=(0, (3, 3)))
        b.text(
            median,
            0.95,
            f" half close\n within {_duration(median)}",
            color=p.muted,
            fontsize=9,
            va="top",
        )
    else:
        no_data(b)
    b.yaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v)))
    panel_header(b, 2, "How long gaps last", "Share of gaps still open after each duration")
    b.set_xlabel(f"Gap outside ±{k:g} bp lasting at least")
    b.set_ylabel("Share of gaps")
    # (c) lead-lag
    xc = pl.DataFrame(r.summary["lead_lag"]["cross_correlation"])
    best_lag = 0
    if xc.height:
        lags = xc["lag_blocks"].to_list()
        corr = xc["corr"].to_list()
        c.bar(lags, corr, color=[p.fees if lag > 0 else p.other for lag in lags], width=0.7)
        best_lag = int(lags[int(np.argmax(corr))])
    else:
        no_data(c)
    c.axhline(0, color=p.muted, lw=0.8)
    c.xaxis.set_major_locator(MaxNLocator(integer=True))
    panel_header(c, 3, "Who moves first", "Pool vs Binance return correlation, by lag")
    c.set_xlabel("Lag in blocks\nPositive = Binance first")
    c.set_ylabel("Correlation of per-block returns")
    lead = (
        f"pool returns follow Binance's {best_lag} block{'s' if best_lag != 1 else ''} later"
        if best_lag > 0
        else "the pool does not lag Binance in this sample"
    )
    frame(
        fig,
        "The pool follows Binance: gaps open, and arbitrage closes them within blocks"
        if best_lag > 0 and len(d) and median <= 60
        else "How the pool tracks Binance",
        f"{pct(inside)} of blocks start inside the fee band; half of the gaps outside "
        f"±{k:g} bp close within {_duration(median) if len(d) else 'n/a'}; {lead}.",
        "Basis = pool price / Binance last trade − 1 at block start, clipped to "
        f"±{BASIS_HIST_RANGE_BP:g} bp. "
        "Lead–lag: correlation of per-block log returns. Sub-project 2.",
    )
    return fig
