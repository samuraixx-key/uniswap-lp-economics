"""Chapter 'Can an LP do better?': the range test, fee curves and hedge risk (figures 14-16,
strategy experiment spec section 9). All three are counterfactual and say so."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import polars as pl
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, NullLocator

from uniswap_lp_economics.strategy.params import (
    BASELINE_FEE_BP,
    HEDGE_DRIFT,
    HEDGE_SYMBOL,
    PEAK_SHARE_FLAG,
    PRIMARY_CAPITAL,
    REPORT_END_US,
    REPORT_START_US,
    TAKER_FEE_BP,
)
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import (
    USD_FMT,
    frame,
    new_figure,
    no_data,
    pal,
    panel_header,
    pct,
)

_START = datetime.fromtimestamp(REPORT_START_US / 1e6, UTC)
_LAST = datetime.fromtimestamp(REPORT_END_US / 1e6, UTC) - timedelta(days=1)
WINDOW = f"{_START:%B}–{_LAST:%B %Y}"
CAVEAT = "ignores how other traders would react to a different "
MODEL_ONLY = "Model only: "


def title_range(verdict: str, delta: float) -> str:
    """The verdict and nothing beyond it (cell intervals are tested against ±delta)."""
    if verdict == "holds":
        return f"No range or rebalancing rule moves fees ÷ LVR by more than {delta:.2f}"
    if verdict == "fails":
        return f"A range or rebalancing rule raises fees ÷ LVR by more than {delta:.2f}"
    return (
        "Inconclusive: the intervals do not settle whether any range or rebalancing rule "
        f"moves fees ÷ LVR by more than {delta:.2f}"
    )


def title_fee(x_bp: float | None, y_share: float | None, model_only: bool) -> str:
    """X and Y only when both exist; "Model only:" when calibration failed."""
    if x_bp is None or y_share is None:
        body = "how the fee level changes what an LP keeps"
        return MODEL_ONLY + body if model_only else body[0].upper() + body[1:]
    body = (
        f"fees cover LVR at about {x_bp:.0f} bp, and the pool stays ahead of 5 bp "
        f"unless it loses {y_share:.0%} of its other volume"
    )
    return MODEL_ONLY + body if model_only else body[0].upper() + body[1:]


def _log_axis(ax: Axes, ticks: Sequence[float], fmt: str = "{:g}") -> None:
    ax.set_xscale("log")
    ax.set_xticks(ticks, [fmt.format(t) for t in ticks])
    ax.xaxis.set_minor_locator(NullLocator())


# ----- figure 14 -----

RULE_LOOK = {  # rule -> (legend label, marker, colour attribute, sideways offset on the log axis)
    "out_of_range": ("Re-centre when out of range", "o", "protocol", 0.9),
    "band": ("Re-centre when outside a band", "s", "fees", 1.0),
    "daily": ("Re-centre every day", "^", "lvr", 1.11),
}


def range_test(r: Results) -> Figure:
    p = pal()
    s = r.summary["strategy"]
    delta = float(s["delta"])
    cells = r.strategy_ranges.filter(
        (pl.col("capital") == PRIMARY_CAPITAL) & pl.col("counted").fill_null(False)
    )
    fig, ax = new_figure(right=0.97)
    ax.axhspan(-delta, delta, color=p.faint, alpha=0.18, lw=0)
    ax.axhline(0, color=p.ink, lw=0.9)
    for rule, (_, marker, color, shift) in RULE_LOOK.items():
        rows = cells.filter(pl.col("rule") == rule).sort("half_width_bp")
        x = [w * shift for w in rows["half_width_bp"].to_list()]
        c = getattr(p, color)
        ax.vlines(x, rows["d_lo"].to_list(), rows["d_hi"].to_list(), color=c, lw=1.6, alpha=0.8)
        for flagged, gid in ((True, "flagged"), (False, "counted")):
            sub = rows.filter(pl.col("flagged") == flagged)
            ax.scatter(
                [w * shift for w in sub["half_width_bp"].to_list()],
                sub["d_ratio"].to_list(),
                s=52,
                marker=marker,
                facecolors="none" if flagged else c,
                edgecolors=c,
                linewidths=1.6,
                zorder=3,
                gid=gid,
            )
    widths = sorted(set(cells["half_width_bp"].to_list()))
    _log_axis(ax, widths, "{:,}")
    ax.set_xlabel("Half-width of the position's range, bp")
    ax.set_ylabel("Δ fees ÷ LVR versus the full-range position")
    ax.annotate(
        f"±{delta:.2f}: the margin that counts as no difference",
        (widths[-1] * 1.12, -delta),
        xytext=(0, -4),
        textcoords="offset points",
        ha="right",
        va="top",
        fontsize=8.5,
        color=p.muted,
    )
    handles = [
        Line2D([], [], ls="", marker=m, color=getattr(p, c), mfc=getattr(p, c), label=name)
        for name, m, c, _ in RULE_LOOK.values()
    ] + [
        Line2D(
            [],
            [],
            ls="",
            marker="o",
            color=p.muted,
            mfc="none",
            mew=1.6,
            label=(
                f"Hollow marker: peak share of active liquidity above {PEAK_SHARE_FLAG:.0%} "
                f"at ${PRIMARY_CAPITAL / 1e6:g}M"
            ),
        )
    ]
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9)
    n, n_flagged = cells.height, int(cells["flagged"].sum())
    depends = s.get("range_verdict_depends_on_flagged_cell")
    frame(
        fig,
        title_range(str(s["range_verdict"]), delta),
        f"Change in fees ÷ LVR against the full-range position, for each re-centring rule and "
        f"range width, {WINDOW}. Marker: point estimate. Bar: 95% day-bootstrap interval. "
        f"{n_flagged} of {n} cells are flagged"
        + (" and the verdict depends on them" if depends else "")
        + ".",
        f"Sub-project 5. Counterfactual, ${PRIMARY_CAPITAL / 1e6:g}M position: ignores how other "
        "traders would react to a different range. Static cells are not drawn. Markers are "
        "offset sideways to keep the rules apart; the width is the same for all three.",
    )
    return fig


# ----- figure 15 -----

FEE_TICKS = [1, 2, 5, 10, 20, 50, 100]


def fee_curves(r: Results) -> Figure:
    p = pal()
    s = r.summary["strategy"]
    delta = float(s["delta"])
    model_only = bool(s.get("fee_model_only"))
    x_bp, y_share = s.get("break_even_fee_bp_x"), s.get("volume_loss_share_at_x_y")
    rows = r.strategy_fees.filter(pl.col("ref_offset_s") == 0)  # the +1 s rows are in the table
    fixed = rows.filter(pl.col("rule").str.starts_with("fixed_")).sort("avg_fee_bp")
    real = r.strategy_fees.filter(pl.col("rule") == "real_pool")
    fig, (a, b) = new_figure(1, 2, right=0.93, wspace=0.34)

    # Panel 1: arbitrage-side fees / LVR.
    fee = fixed["avg_fee_bp"].to_list()
    ratio = fixed["arb_ratio"].to_list()
    base = float(fixed.filter(pl.col("avg_fee_bp") == BASELINE_FEE_BP)["arb_ratio"][0])
    a.plot(fee, ratio, color=p.fees, lw=2, marker="o", ms=5, zorder=3, gid="fixed")
    a.axhline(base + delta, color=p.lvr, lw=1.1, ls=(0, (4, 3)))
    a.annotate(
        f"+δ above the {BASELINE_FEE_BP:g} bp value  ({base + delta:.2f})",
        (100, base + delta),
        xytext=(0, 4),
        textcoords="offset points",
        ha="right",
        fontsize=8.5,
        color=p.lvr,
    )
    dyn = rows.filter(pl.col("rule").str.contains("^(vol|move)_"))
    for prefix, name, color, marker in (
        ("vol_", "Volatility-linked fee", p.jit, "D"),
        ("move_", "Move-linked fee", p.builder, "v"),
    ):
        d = dyn.filter(pl.col("rule").str.starts_with(prefix))
        a.scatter(
            d["arb_fee_bp"].to_list(),
            d["arb_ratio"].to_list(),
            s=34,
            marker=marker,
            color=color,
            zorder=4,
            label=name,
        )
    oracle = rows.filter(pl.col("rule") == "oracle")
    if oracle.height:
        ox, oy = float(oracle["arb_fee_bp"][0]), float(oracle["arb_ratio"][0])
        a.scatter([ox], [oy], s=90, marker="*", color=p.protocol, zorder=4)
        a.annotate(
            "oracle fee: arbitrage pays\nits 100 bp cap",
            (ox, oy),
            xytext=(-6, -14),
            textcoords="offset points",
            ha="right",
            fontsize=8.5,
            color=p.protocol,
        )
    if real.height:
        a.scatter(
            [BASELINE_FEE_BP],
            [float(real["arb_ratio"][0])],
            s=60,
            marker="D",
            facecolors="none",
            edgecolors=p.ink,
            linewidths=1.5,
            zorder=4,
            label="Real pool at 5 bp",
        )
    a.legend(loc="lower right", frameon=False, fontsize=8.5)
    _log_axis(a, FEE_TICKS)
    a.set_xlabel("Fee charged to the arbitrage, bp")
    a.set_ylabel("Arbitrage-side fees ÷ LVR")
    panel_header(
        a,
        1,
        "Fees ÷ LVR on arbitrage flow",
        "Line: fixed fee levels. Markers: dynamic rules at the fee they charged arbitrage.",
    )

    # Panel 2: break-even volume loss (left axis) and whole-pool fees / LVR (right axis).
    above = fixed.filter(pl.col("avg_fee_bp") >= BASELINE_FEE_BP)
    b.plot(
        above["avg_fee_bp"].to_list(),
        above["break_even_share"].to_list(),
        color=p.lvr,
        lw=2,
        marker="o",
        ms=5,
        zorder=3,
    )
    b.set_ylim(0, 1.05)
    b.yaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v)))
    b.set_ylabel("Other volume the pool can lose, share", color=p.lvr)
    _log_axis(b, FEE_TICKS)
    b.set_xlabel("Fixed fee level, bp")
    pool = b.twinx()
    pool.plot(fee, fixed["pool_ratio"].to_list(), color=p.fees, lw=2, marker="s", ms=4.5)
    pool.axhline(1, color=p.fees, lw=0.9, ls=(0, (4, 3)))
    pool.set_yscale("log")
    pool.set_ylim(0.04, 9)  # puts 1 well clear of the break-even share at X
    pool.set_yticks([0.1, 0.25, 0.5, 1, 2, 4, 8], ["0.1", "0.25", "0.5", "1", "2", "4", "8"])
    pool.yaxis.set_minor_locator(NullLocator())
    pool.set_ylabel("Whole-pool fees ÷ LVR", color=p.fees)
    pool.grid(False)
    if real.height:
        pool.scatter(
            [BASELINE_FEE_BP],
            [float(real["pool_ratio"][0])],
            s=60,
            marker="D",
            facecolors="none",
            edgecolors=p.ink,
            linewidths=1.5,
            zorder=4,
        )
    if x_bp is not None:
        b.axvline(x_bp, color=p.ink, lw=1, ls=(0, (2, 2)))
        pool.scatter([x_bp], [1], s=70, color=p.fees, zorder=5)
        pool.annotate(
            f"X ≈ {x_bp:.0f} bp: fees = LVR",
            (x_bp, 1),
            xytext=(-8, 10),
            textcoords="offset points",
            ha="right",
            fontsize=9,
            fontweight="bold",
            color=p.fees,
        )
        if y_share is not None:
            b.scatter([x_bp], [y_share], s=70, color=p.lvr, zorder=5)
            b.annotate(
                f"Y = {y_share:.0%} of other volume",
                (x_bp, y_share),
                xytext=(8, -12),
                textcoords="offset points",
                fontsize=9,
                fontweight="bold",
                color=p.lvr,
            )
    handles = [
        Line2D([], [], color=p.lvr, lw=2, marker="o", ms=5, label="Other volume the pool can lose"),
        Line2D([], [], color=p.fees, lw=2, marker="s", ms=4.5, label="Whole-pool fees ÷ LVR"),
    ]
    if real.height:
        handles.append(
            Line2D(
                [],
                [],
                ls="",
                marker="D",
                mfc="none",
                color=p.ink,
                mew=1.5,
                label=f"Real pool at 5 bp: {float(real['pool_ratio'][0]):.2f}",
            )
        )
    b.legend(handles=handles, loc="upper left", frameon=False, fontsize=8.5)
    panel_header(
        b,
        2,
        "Whole pool, and what it can lose",
        "Left axis: other volume lost before no better off than at 5 bp. Right: fees ÷ LVR.",
    )
    five = fixed.filter(pl.col("avg_fee_bp") == BASELINE_FEE_BP)
    cuts = r.strategy_fees.filter(pl.col("rule") == "protocol_cut_0")
    sub = (
        f"Arbitrage-side fees ÷ LVR at {BASELINE_FEE_BP:g} bp is {float(five['arb_ratio'][0]):.2f} "
        f"in the model and {float(real['arb_ratio'][0]):.2f} in the real pool"
        + (", so read the curves for direction, not level" if model_only else "")
        + ". "
        + (
            f"Whole-pool fees ÷ LVR reaches 1 at X = {x_bp:.1f} bp; there the pool can lose "
            f"Y = {y_share:.0%} of its other volume before it is no better off than at 5 bp."
            if x_bp is not None and y_share is not None
            else ""
        )
    )
    frame(
        fig,
        title_fee(x_bp, y_share, model_only),
        sub,
        f"Sub-project 5, {WINDOW}, reference price read at slot start (+1 s is in the table). "
        f"Counterfactual: {CAVEAT}fee; other volume is lost in proportion, the price path is "
        "fixed."
        + (
            " Model-only: July calibration failed, so no fee result is tested."
            if model_only
            else ""
        )
        + (
            f" Arithmetic: with no protocol cut the real pool's whole-pool fees ÷ LVR at 5 bp "
            f"would be {float(cuts['pool_ratio'][0]):.2f}."
            if cuts.height and real.height
            else ""
        ),
    )
    return fig


# ----- figure 16 -----

HEDGE_LABEL = {
    "never": "unhedged",
    "daily": "hedged daily",
    "hourly": "hedged hourly",
    "drift": f"hedged at {HEDGE_DRIFT:.0%} drift",
    "rebalancing_benchmark": "rebalancing benchmark",
}
HEDGE_PHRASE = {"daily": "daily", "hourly": "hourly", "drift": f"at {HEDGE_DRIFT:.0%} drift"}


def _strategy_name(name: str) -> str:
    if name == "full_range":
        return "Full-range position"
    return f"Band position, ±{int(name.split('_')[1].removesuffix('bp')):,} bp"


def hedge_risk(r: Results) -> Figure:
    p = pal()
    rows = r.strategy_hedge.filter(
        pl.col("taker_fee_bp").is_null() | pl.col("taker_fee_bp").is_in([0.0, TAKER_FEE_BP])
    )
    names = list(dict.fromkeys(rows["strategy"].to_list()))
    fig, axes = new_figure(1, len(names), right=0.96, wspace=0.08, sharex=True, sharey=True)
    fig.set_label("hedge")
    for number, (ax, name) in enumerate(zip(axes, names, strict=True), start=1):
        own = rows.filter(pl.col("strategy") == name)
        ax.axhline(0, color=p.muted, lw=0.8)
        looks = {
            "never": (p.lvr, "o"),
            "daily": (p.fees, "o"),
            "hourly": (p.fees, "o"),
            "drift": (p.fees, "o"),
            "rebalancing_benchmark": (p.ink, "D"),
        }
        wants = []
        for rule, (color, marker) in looks.items():
            row = own.filter(pl.col("rule") == rule)
            if not row.height:
                continue
            x, y = float(row["sd_daily_usd_per_1m"][0]), float(row["mean_daily_usd_per_1m"][0])
            ax.scatter([x], [y], s=70, color=color, marker=marker, zorder=3, gid="hedge")
            wants.append((rule, x, y))
        for rule, x, y in wants:
            left = x < (60 if rule == "rebalancing_benchmark" else 300)  # keep labels on canvas
            dx, dy, ha, va = {
                "never": (-10, 0, "right", "center"),
                "daily": (9, 5, "left", "bottom"),
                "hourly": (9, 8, "left", "bottom") if left is False else (-8, 8, "right", "bottom"),
                "drift": (9, -12, "left", "top"),
                "rebalancing_benchmark": (9, -12, "left", "top")
                if left
                else (-9, 8, "right", "bottom"),
            }[rule]
            ax.annotate(
                HEDGE_LABEL[rule],
                (x, y),
                xytext=(dx, dy),
                textcoords="offset points",
                ha=ha,
                va=va,
                fontsize=9,
                color=p.lvr if rule == "never" else p.ink,
            )
        ax.set_xscale("log")
        ax.set_yscale("symlog", linthresh=200)
        ax.set_xticks(
            [30, 100, 300, 1000, 3000, 10000], ["$30", "$100", "$300", "$1k", "$3k", "$10k"]
        )
        ax.set_ylim(-500, 5000)  # room under the lowest label
        ax.set_yticks([-200, 0, 200, 1000, 3000])
        ax.yaxis.set_major_formatter(USD_FMT)
        ax.xaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_minor_locator(NullLocator())
        ax.set_xlabel("Spread (SD) of daily P&L, USD per $1M")
        if number == 1:
            ax.set_ylabel("Mean daily P&L, USD per $1M")
        panel_header(
            ax, number, _strategy_name(name), "Unhedged, hedged by rule, and the benchmark"
        )
    if not rows.height:
        no_data(axes[0])
    full = rows.filter((pl.col("strategy") == "full_range") & (pl.col("rule") != "never"))
    hedged = full.filter(pl.col("rule").is_in(list(HEDGE_PHRASE))).sort("sd_daily_usd_per_1m")
    never = rows.filter((pl.col("strategy") == "full_range") & (pl.col("rule") == "never"))
    if hedged.height and never.height:
        k = float(never["sd_daily_usd_per_1m"][0]) / float(hedged["sd_daily_usd_per_1m"][0])
        head = (
            f"Hedging {HEDGE_PHRASE[hedged['rule'][0]]} cuts the spread of a full-range "
            f"position's daily P&L about {float(f'{k:.2g}'):.0f}-fold"
        )
    else:
        head = "How a perpetual hedge changes the spread of daily P&L"
    frame(
        fig,
        head,
        f"Mean against spread of daily P&L for a ${PRIMARY_CAPITAL / 1e6:g}M position, {WINDOW}. "
        f"Hedge trades pay a {TAKER_FEE_BP:g} bp taker fee. The hedge removes the price exposure "
        "that dominates the unhedged mean and spread. Diamond: the rebalancing benchmark, fees "
        "− LVR − gas − trade, with no hedge.",
        f"Sub-project 5. Counterfactual: {CAVEAT}range or hedge. Hedge: Binance {HEDGE_SYMBOL} "
        "perpetual, reset at minute closes, funding included. The hedge changes risk, "
        "not fees − LVR.",
    )
    return fig
