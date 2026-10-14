"""Charts for results/figures (spec section 8). Every chart renders, even from empty input
(a "no data" panel), so a quiet sub-sample never breaks `ulpe analyze`."""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter  # noqa: E402

from uniswap_lp_economics.config import HORIZONS_S  # noqa: E402

HORIZON_LABELS = {0: "0s", 12: "12s", 60: "1m", 300: "5m", 3600: "1h"}
WATERFALL_STEPS = [
    ("available_usd", "available"),
    ("captured_searchers_usd", "captured\n(searchers)"),
    ("top_bot_single_pool_gross_usd", "top bots\nsingle-pool gross"),
    ("gas_burned_usd", "- base fee\nburned"),
    ("priority_fee_usd", "- priority\nfee"),
    ("coinbase_usd", "- coinbase\npayment"),
    ("kept_usd", "kept\n(upper bound)"),
]
DURATION_TICKS_S = (12, 24, 60, 120, 300, 600, 1800)


def _save(fig: Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _no_data(ax: Axes) -> None:
    ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)


def _floats(s: pl.Series) -> list[float]:
    return [math.nan if v is None else float(v) for v in s.to_list()]


def markout_curves(by_label: pl.DataFrame, path: Path) -> None:
    """Chart 1 (headline): notional-weighted trader markout by flow label, with 95% bands."""
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = sorted(set(by_label["flow_label"].to_list())) if by_label.height else []
    for label in labels:
        g = by_label.filter(pl.col("flow_label") == label).sort("horizon_s")
        x = [HORIZONS_S.index(h) for h in g["horizon_s"].to_list()]
        ax.plot(x, _floats(g["mean_bp"]), marker="o", label=label)
        ax.fill_between(x, _floats(g["ci_lo_bp"]), _floats(g["ci_hi_bp"]), alpha=0.15)
    if labels:
        ax.legend(title="flow")
    else:
        _no_data(ax)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_xticks(range(len(HORIZONS_S)), [HORIZON_LABELS.get(h, f"{h}s") for h in HORIZONS_S])
    ax.set_xlabel("time after the block")
    ax.set_ylabel("trader markout vs Binance (bp of notional)")
    ax.set_title("Who wins against the pool? Markouts by flow type (95% day-bootstrap bands)")
    _save(fig, path)


def basis_histogram(series: pl.DataFrame, path: Path, band_bp: float) -> None:
    """Chart 2: pool vs Binance basis at block start, with the fee band."""
    fig, ax = plt.subplots(figsize=(8, 5))
    b = series["basis_bp"].drop_nulls().drop_nans().clip(-50.0, 50.0).to_numpy()
    if len(b):
        ax.hist(b, bins=200, color="tab:blue")
    else:
        _no_data(ax)
    for x in (-band_bp, band_bp):
        ax.axvline(x, color="tab:red", ls="--", lw=1)
    ax.set_xlabel("basis at block start (bp, clipped to +/-50)")
    ax.set_ylabel("blocks")
    ax.set_title(f"How far apart are the venues? Dashed: +/-{band_bp:g} bp fee band")
    _save(fig, path)


def duration_ticks(lo: float, hi: float) -> list[int]:
    """Major ticks for the log duration axis: the round durations inside [lo, hi]."""
    return [t for t in DURATION_TICKS_S if lo <= t <= hi]


def episode_chart(episodes: pl.DataFrame, summary: pl.DataFrame, path: Path) -> None:
    """Chart 3: how long gap episodes last, and who closes them."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    d = np.sort(episodes["duration_s"].drop_nulls().to_numpy()) if episodes.height else np.empty(0)
    if len(d):
        ax1.step(d, 1.0 - np.arange(1, len(d) + 1) / len(d), where="post")
        ax1.set_xscale("log")
        # Explicit round-second ticks: the default log labels overlap on this short range.
        ax1.xaxis.set_major_locator(FixedLocator(duration_ticks(float(d[0]), float(d[-1]))))
        ax1.xaxis.set_major_formatter(ScalarFormatter())
        ax1.xaxis.set_minor_formatter(NullFormatter())
    else:
        _no_data(ax1)
    ax1.set_xlabel("episode duration (s)")
    ax1.set_ylabel("share of episodes lasting longer")
    ax1.set_title("How long do gaps last?")
    if summary.height:
        ax2.bar(
            summary["closer"].to_list(), _floats(summary["share_gap_weight"]), color="tab:orange"
        )
        ax2.tick_params(axis="x", rotation=30)
    else:
        _no_data(ax2)
    ax2.set_ylabel("share of gap-weighted time")
    ax2.set_title("Who closes the gap?")
    _save(fig, path)


def waterfall_chart(w: dict[str, float], path: Path) -> None:
    """Chart 4: available -> captured -> costs -> kept."""
    fig, ax = plt.subplots(figsize=(11, 5))
    values = []
    for key, _ in WATERFALL_STEPS:
        v = w.get(key)
        values.append(v / 1e6 if v is not None and math.isfinite(v) else 0.0)
    colors = ["tab:blue"] * 3 + ["tab:red"] * 3 + ["tab:green"]
    names = [label for _, label in WATERFALL_STEPS]
    ax.bar(names, values, color=colors)
    for i, v in enumerate(values):
        ax.annotate(f"{v:,.2f}", (i, v), ha="center", va="bottom", fontsize=8)
    if not w:
        _no_data(ax)
    ax.set_ylabel("USD millions")
    ax.set_title("Arbitrage: available -> captured -> kept after gas and builder payments")
    _save(fig, path)


def cross_correlation_chart(xc: pl.DataFrame, path: Path) -> None:
    """Chart 5: correlation of pool returns with lagged Binance returns."""
    fig, ax = plt.subplots(figsize=(8, 5))
    if xc.height:
        ax.bar(xc["lag_blocks"].to_list(), _floats(xc["corr"]), color="tab:purple")
    else:
        _no_data(ax)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_xlabel("lag (blocks); positive = Binance moved first")
    ax.set_ylabel("correlation of per-block log returns")
    ax.set_title("Lead-lag: pool vs Binance")
    _save(fig, path)


def bot_profit_chart(bot_profit: pl.DataFrame, path: Path) -> None:
    """Chart 6: gross vs kept per top bot (single-pool transactions)."""
    fig, ax = plt.subplots(figsize=(11, 5))
    bots = bot_profit.filter(pl.col("sender") != "TOTAL") if bot_profit.height else bot_profit
    if bots.height:
        x = np.arange(bots.height)
        ax.bar(x - 0.2, [v / 1e3 for v in _floats(bots["gross_usd"])], width=0.4, label="gross")
        ax.bar(x + 0.2, [v / 1e3 for v in _floats(bots["kept_usd"])], width=0.4, label="kept")
        short = [f"{a[:6]}...{a[-4:]}" for a in bots["sender"].to_list()]
        ax.set_xticks(x, short, rotation=45, ha="right")
        ax.legend()
    else:
        _no_data(ax)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_ylabel("USD thousands")
    ax.set_title("Top bots: gross 0s markout vs kept (upper bound), single-pool transactions")
    _save(fig, path)
