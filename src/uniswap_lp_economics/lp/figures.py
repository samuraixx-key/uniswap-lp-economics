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
    """Chart 10: bp of position value per day by LP type and by range width, with 95% intervals.
    JIT gets its own panel: one 12 s slot of capital makes its rate thousands of bp per day,
    which would flatten the other LP types on a shared axis."""
    fig, axes = plt.subplots(
        1, 3, figsize=(15, 5), gridspec_kw={"width_ratios": [4, 1.3, 5]}, layout="constrained"
    )
    is_jit = pl.col("group") == "jit"
    panels = (
        ("lp_type", ~is_jit, "by LP type (without JIT)"),
        ("lp_type", is_jit, "JIT (own scale)"),
        ("width_bucket", pl.lit(True), "by range width"),
    )
    for ax, (grouping, keep, title) in zip(axes, panels, strict=True):
        g = groups.filter((pl.col("grouping") == grouping) & keep) if groups.height else groups
        if g.height:
            y = np.array(floats(g["bp_per_day"]))
            lo = np.maximum(y - np.array(floats(g["ci_lo_bp"])), 0)
            hi = np.maximum(np.array(floats(g["ci_hi_bp"])) - y, 0)
            ax.bar(g["group"].to_list(), y, yerr=[lo, hi], color="tab:green", capsize=3)
            ax.tick_params(axis="x", rotation=30)
        else:
            no_data(ax)
        ax.axhline(0.0, color="grey", lw=0.8)
        ax.set_title(f"P&L vs rebalancing, {title}", fontsize=10)
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


# (value key, label, kind, share key). Pool LVR first, then LVR on other flows (which is not
# searcher LVR) comes off it; the rest is the chain of the LVR on searcher swaps.
DESTINATION_STEPS = [
    ("pool_lvr_0_usd", "pool LVR\n(0 s)", "total", None),
    ("lvr_on_other_flows_usd", "- other flows\n(no searcher)", "down", None),
    ("lvr_on_searcher_swaps_usd", "searcher\nLVR", "total", None),
    ("fees_on_searcher_swaps_usd", "- LP fees", "down", "share_fees"),
    ("protocol_fees_on_searcher_swaps_usd", "- protocol\nfees", "down", "share_protocol_fees"),
    ("multi_pool_gross_usd", "- multi-pool\n(no split)", "down", "share_multi_pool"),
    ("gas_burned_usd", "- gas\nburned", "down", "share_gas_burned"),
    ("builder_margin_usd", "- builder\nmargin", "down", "share_builder_margin"),
    ("proposer_usd", "- proposer", "down", "share_proposer"),
    ("searcher_kept_usd", "searcher kept\n(upper bound)", "total", "share_searcher_kept"),
]


def destination_waterfall(d: dict[str, float], path: Path) -> None:
    """Chart 12: where LVR goes, as a floating waterfall (shares are of searcher-step LVR)."""
    fig, ax = plt.subplots(figsize=(14, 5))
    if not d:
        no_data(ax)
    else:
        level = 0.0
        tops, bottoms = [0.0], [0.0]
        for i, (key, _label, kind, share_key) in enumerate(DESTINATION_STEPS):
            v = d.get(key, 0.0) / 1e3
            before = level
            if kind == "total":
                ax.bar(i, v, color="tab:blue")
                level = v
            else:
                ax.bar(i, -v, bottom=level, color="tab:grey" if i == 1 else "tab:red")
                level -= v
            tops.append(max(before, level))
            bottoms.append(min(before, level))
            text = f"{v:,.1f}"
            if share_key is not None and share_key in d:
                text += f"\n{d[share_key]:.1%}"
            ax.annotate(
                text,
                (i, max(before, level)),
                ha="center",
                va="bottom",
                fontsize=8,
            )
        ax.set_xticks(range(len(DESTINATION_STEPS)), [s[1] for s in DESTINATION_STEPS])
        # Headroom for the two-line value labels above the tallest bar, clear of the title.
        span = max(max(tops) - min(bottoms), 1e-9)
        ax.set_ylim(min(bottoms) - 0.05 * span, max(tops) + 0.2 * span)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_ylabel("USD thousands")
    ax.set_title("Where LVR goes: fees, gas, builders, proposers, searchers (primary split)")
    save_figure(fig, path)
