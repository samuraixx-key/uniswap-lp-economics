"""Charts 7-11 (spec section 10). Every chart renders even from empty input."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from uniswap_lp_economics.figures import floats, no_data, save_figure  # noqa: E402


def fees_vs_lvr_daily(daily: pl.DataFrame, path: Path) -> None:
    """Chart 7: daily LP fees vs measured LVR."""
    fig, ax = plt.subplots(figsize=(10, 5))
    if daily.height:
        x = daily["day"].to_list()
        ax.plot(x, [v / 1e3 for v in floats(daily["fees_usd"])], label="LP fees")
        ax.plot(x, [v / 1e3 for v in floats(daily["lvr_0"])], label="LVR (0 s)")
        ax.plot(x, [v / 1e3 for v in floats(daily["lvr_12"])], ls="--", label="LVR (12 s)")
        ax.legend()
        fig.autofmt_xdate()
    else:
        no_data(ax)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_ylabel("USD thousands per day")
    ax.set_title("Do fees cover LVR? Daily LP fees vs measured LVR")
    save_figure(fig, path)


def measured_vs_theory(daily: pl.DataFrame, path: Path) -> None:
    """Chart 8: measured arbitrage LVR vs theory, with and without the P_trade adjustment."""
    fig, ax = plt.subplots(figsize=(10, 5))
    if daily.height:
        x = daily["day"].to_list()
        ax.plot(x, [v / 1e3 for v in floats(daily["lvr_0_searcher"])], label="measured (searchers)")
        ax.plot(x, [v / 1e3 for v in floats(daily["theory_1s"])], label="theory: sigma^2/8")
        ax.plot(x, [v / 1e3 for v in floats(daily["theory_arb"])], label="theory x P_trade")
        ax.legend()
        fig.autofmt_xdate()
    else:
        no_data(ax)
    ax.set_ylabel("USD thousands per day")
    ax.set_title("Measured vs theoretical LVR")
    save_figure(fig, path)


def regime_chart(summary: pl.DataFrame, path: Path) -> None:
    """Chart 9: fees - LVR by volatility tercile."""
    fig, ax = plt.subplots(figsize=(8, 5))
    if summary.height and "fees_minus_lvr_usd" in summary.columns:
        ax.bar(
            summary["regime"].to_list(),
            [v / 1e3 for v in floats(summary["fees_minus_lvr_usd"])],
            color="tab:blue",
        )
    else:
        no_data(ax)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_ylabel("fees - LVR, USD thousands")
    ax.set_title("LP result by volatility regime (daily realised volatility terciles)")
    save_figure(fig, path)


def group_chart(groups: pl.DataFrame, path: Path) -> None:
    """Chart 10: bp of position value per day by LP type and by range width, with 95% intervals."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, grouping in zip(axes, ("lp_type", "width_bucket"), strict=True):
        g = groups.filter(pl.col("grouping") == grouping) if groups.height else groups
        if g.height:
            y = np.array(floats(g["bp_per_day"]))
            lo = np.maximum(y - np.array(floats(g["ci_lo_bp"])), 0)
            hi = np.maximum(np.array(floats(g["ci_hi_bp"])) - y, 0)
            ax.bar(g["group"].to_list(), y, yerr=[lo, hi], color="tab:green", capsize=3)
            ax.tick_params(axis="x", rotation=30)
        else:
            no_data(ax)
        ax.axhline(0.0, color="grey", lw=0.8)
        ax.set_title(f"P&L vs rebalancing by {grouping.replace('_', ' ')}")
        ax.set_ylabel("bp of position value per day")
    save_figure(fig, path)


def lifetime_chart(by_width: pl.DataFrame, by_life: pl.DataFrame, path: Path) -> None:
    """Chart 11: share of window-active positions that beat holding over their lifetime."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, df, col in ((axes[0], by_width, "width_bucket"), (axes[1], by_life, "life_bucket")):
        if df.height:
            ax.bar(df[col].to_list(), floats(df["share_beat_hold"]), color="tab:purple")
            ax.set_ylim(0, 1)
            ax.tick_params(axis="x", rotation=30)
        else:
            no_data(ax)
        ax.axhline(0.5, color="grey", lw=0.8, ls="--")
        ax.set_title(f"Beat holding, by {col.replace('_', ' ')}")
        ax.set_ylabel("share of positions")
    save_figure(fig, path)
