"""Chapter 'Who wins against the pool?' (figure 4): markout small multiples by flow label."""

import numpy as np
import polars as pl
from matplotlib.figure import Figure

from uniswap_lp_economics.config import HORIZONS_S
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import fade_band, frame, new_figure, no_data, pal

HORIZON_LABELS = {0: "0 s", 12: "12 s", 60: "1 m", 300: "5 m", 3600: "1 h"}
FLOW_NAMES = {
    "searcher": "Searchers",
    "aggregator": "Aggregators",
    "uniswap_router": "Uniswap router",
    "intent_settlement": "Intent settlement",
    "other_contract": "Other contracts",
}


def _bp(x: float, digits: int) -> str:
    """Signed basis points with a typographic minus."""
    return f"{x:+.{digits}f} bp".replace("-", "−")


def _name(label: str) -> str:
    return FLOW_NAMES.get(label, label.replace("_", " ").capitalize())


def markouts(r: Results) -> Figure:
    p = pal()
    m = r.markouts
    by = m.filter(pl.col("grouping") == "flow_label")
    everyone = m.filter(pl.col("grouping") == "all").sort("horizon_s")
    labels = sorted(
        {str(x) for x in by["flow_label"].to_list()}, key=lambda s: (s != "searcher", s)
    )
    fig, axes = new_figure(1, max(len(labels), 1), sharey=True, top=0.74, bottom=0.17, wspace=0.08)
    axes = np.atleast_1d(axes)
    if not labels:
        no_data(axes[0])
    x_all = [HORIZONS_S.index(h) for h in everyone["horizon_s"].to_list()]
    for ax, label in zip(axes, labels, strict=False):
        g = by.filter(pl.col("flow_label") == label).sort("horizon_s")
        x = [HORIZONS_S.index(h) for h in g["horizon_s"].to_list()]
        color = p.lvr if label == "searcher" else p.fees
        fade_band(ax, x, g["ci_lo_bp"].to_list(), g["ci_hi_bp"].to_list(), color)
        if everyone.height:
            ax.plot(x_all, everyone["mean_bp"].to_list(), color=p.faint, lw=1.2, ls=(0, (4, 3)))
        mean = g["mean_bp"].to_list()
        ax.plot(x, mean, color=color, lw=2.2, marker="o", ms=4)
        ax.axhline(0, color=p.muted, lw=0.8)
        ax.annotate(
            _bp(mean[0], 1),
            (x[0], mean[0]),
            xytext=(2, 9),
            textcoords="offset points",
            fontsize=9,
            color=color,
            fontweight="bold",
        )
        ax.set_title(_name(label), loc="left", fontsize=11, fontweight="bold", color=color)
        ax.set_xticks(
            range(len(HORIZONS_S)),
            [HORIZON_LABELS.get(h, f"{h} s") for h in HORIZONS_S],
            fontsize=8.5,
        )
        ax.set_xlim(-0.8, len(HORIZONS_S) - 0.6)
    axes[0].set_ylabel("Trader markout vs Binance (bp of notional)")
    s0 = by.filter((pl.col("flow_label") == "searcher") & (pl.col("horizon_s") == 0))
    others0 = by.filter((pl.col("flow_label") != "searcher") & (pl.col("horizon_s") == 0))
    claim = (
        s0.height > 0
        and float(s0["mean_bp"][0]) > 0
        and others0.height > 0
        and float((others0["mean_bp"] < 0).mean()) > 0.5  # type: ignore[arg-type]
    )
    a0 = everyone.filter(pl.col("horizon_s") == 0)
    s_txt = f"searchers {_bp(float(s0['mean_bp'][0]), 2)}" if s0.height else "no searcher flow"
    a_txt = f"all swaps {_bp(float(a0['mean_bp'][0]), 2)}" if a0.height else ""
    frame(
        fig,
        "Searchers win against the pool; most other flow pays"
        if claim
        else "Trader markouts by flow type",
        f"Notional-weighted trader markout after the swap fee, 0 s to 1 h after the block. "
        f"At 0 s: {s_txt}; {a_txt}.",
        "Positive = the swap beat Binance's last trade at that horizon. Bands: 95% bootstrap "
        "over days (1,000 resamples). Dashed: all swaps. Sub-project 2.",
    )
    return fig
