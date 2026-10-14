"""Charts 7-12 (spec section 10). Every chart renders even from empty input."""

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


DESTINATION_STEPS = [
    ("lvr_searcher_usd", "LVR on\nsearcher swaps", "total"),
    ("lp_fees_searcher_usd", "- LP fees", "down"),
    ("protocol_fees_searcher_usd", "- protocol\nfees", "down"),
    ("multi_pool_gross_usd", "- multi-pool\n(no split)", "down"),
    ("gas_burned_usd", "- gas\nburned", "down"),
    ("builder_margin_usd", "- builder\nmargin", "down"),
    ("proposer_usd", "- proposer", "down"),
    ("searcher_kept_usd", "searcher kept\n(upper bound)", "total"),
]


def destination_waterfall(d: dict[str, float], path: Path) -> None:
    """Chart 12: where LVR goes, as a floating waterfall."""
    fig, ax = plt.subplots(figsize=(12, 5))
    if not d:
        no_data(ax)
    else:
        level = 0.0
        for i, (key, _label, kind) in enumerate(DESTINATION_STEPS):
            v = d.get(key, 0.0) / 1e3
            if kind == "total":
                ax.bar(i, v, color="tab:blue")
                level = v
            else:
                ax.bar(i, -v, bottom=level, color="tab:red")
                level -= v
            ax.annotate(
                f"{v:,.1f}",
                (i, max(level, v if kind == "total" else level)),
                ha="center",
                va="bottom",
                fontsize=8,
            )
        ax.set_xticks(range(len(DESTINATION_STEPS)), [s[1] for s in DESTINATION_STEPS])
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_ylabel("USD thousands")
    ax.set_title("Where LVR goes: fees, gas, builders, proposers, searchers")
    save_figure(fig, path)
