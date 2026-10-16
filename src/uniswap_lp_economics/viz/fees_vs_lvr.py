"""Chapter 'How big is LVR, and when?': LVR and fees against volatility (figure 5), cumulative
fees vs LVR (figure 6) and measured vs theoretical LVR (figure 7)."""

from collections.abc import Sequence

import numpy as np
import polars as pl
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from numpy.typing import ArrayLike

from uniswap_lp_economics.viz.data import Results, window_label
from uniswap_lp_economics.viz.style import USD_FMT, frame, new_figure, no_data, pal, pct, usd


def _source(r: Results) -> str:
    return (
        f"Uniswap V3 USDC/WETH 0.05%, {window_label(r.daily)}. LVR measured per swap against "
        "Binance's last trade at block time."
    )


def fit_loglog(
    x: Sequence[float] | ArrayLike, y: Sequence[float] | ArrayLike
) -> tuple[float, float]:
    """OLS of log y on log x: (slope, intercept)."""
    slope, intercept = np.polyfit(np.log(np.asarray(x, float)), np.log(np.asarray(y, float)), 1)
    return float(slope), float(intercept)


def break_even(a: tuple[float, float], b: tuple[float, float]) -> float:
    """x where the two log-log fits cross; NaN for parallel fits."""
    if a[0] == b[0]:
        return float("nan")
    return float(np.exp((b[1] - a[1]) / (a[0] - b[0])))


def lvr_vs_volatility(r: Results) -> Figure:
    p = pal()
    d = r.daily.with_columns(total_fees=pl.col("fees_usd") + pl.col("protocol_fee_usd"))
    fig, ax = new_figure(right=0.84)
    pos = d.filter(
        (pl.col("sigma_annual") > 0) & (pl.col("lvr_0") > 0) & (pl.col("total_fees") > 0)
    )
    if pos.height < 2:
        no_data(ax, "too few days with positive LVR and fees")
        frame(fig, "LVR and swap fees against daily volatility", "Not enough data.", _source(r))
        return fig
    sig = pos["sigma_annual"].to_numpy()
    lvr_fit = fit_loglog(sig, pos["lvr_0"].to_list())
    fee_fit = fit_loglog(sig, pos["total_fees"].to_list())
    th = d.filter((pl.col("sigma_annual") > 0) & (pl.col("theory_1s") > 0))
    ax.scatter(th["sigma_annual"], th["theory_1s"], s=10, color=p.faint, alpha=0.7, lw=0, zorder=2)
    xs = np.linspace(sig.min() * 0.95, sig.max() * 1.05, 200)
    for y, (b, a), c, name, dy in (
        (pos["lvr_0"], lvr_fit, p.lvr, "LVR", 16),
        (pos["total_fees"], fee_fit, p.fees, "Swap fees", -16),
    ):
        ax.scatter(sig, y, s=34, color=c, alpha=0.55, edgecolor=p.background, lw=0.6, zorder=3)
        fit = np.exp(a) * xs**b
        ax.plot(xs, fit, color=c, lw=2.2, zorder=4)
        ax.annotate(
            name + "\n" + r"$\propto \sigma^{" + f"{b:.2f}" + "}$",
            (xs[-1], fit[-1]),
            xytext=(6, dy),
            textcoords="offset points",
            color=c,
            fontsize=11,
            fontweight="bold",
            va="center",
            ha="left",
            annotation_clip=False,
            parse_math=True,
        )
    ax.text(
        xs[-1],
        th["theory_1s"].min() if th.height else 1.0,
        "grey: LVR formula\n(1 s returns)",
        color=p.faint,
        fontsize=9,
        ha="left",
        va="bottom",
    )
    s_star = break_even(lvr_fit, fee_fit)
    crosses = bool(np.isfinite(s_star)) and sig.min() <= s_star <= sig.max()
    if crosses:
        ax.axvline(s_star, color=p.muted, lw=1, ls=(0, (3, 3)), zorder=1)
        ymax = ax.get_ylim()[1]
        ax.text(
            s_star * 0.96,
            ymax,
            "← fees exceed LVR",
            ha="right",
            va="top",
            color=p.fees,
            fontsize=10,
            fontstyle="italic",
        )
        ax.text(
            s_star * 1.04,
            ymax,
            "LVR exceeds fees →",
            ha="left",
            va="top",
            color=p.lvr,
            fontsize=10,
            fontstyle="italic",
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v)))
    ax.xaxis.set_minor_formatter(
        FuncFormatter(lambda v, _: pct(v) if round(v, 2) in (0.3, 0.5, 0.7) else "")
    )
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.grid(True, axis="both", which="major")
    ax.set_xlabel("Daily realised volatility of ETH on Binance (annualised, log scale)")
    ax.set_ylabel("USD per day (log scale)")
    tail = (
        f" Above about {pct(s_star)} volatility the pool pays more to arbitrage than it earns "
        "in fees."
        if crosses
        else ""
    )
    frame(
        fig,
        "Arbitrage losses grow faster with volatility than fees do"
        if lvr_fit[0] > fee_fit[0]
        else "LVR and swap fees against daily volatility",
        f"Each dot is one day. Swap fees (LP + protocol) grow as σ^{fee_fit[0]:.2f}, LVR as "
        f"σ^{lvr_fit[0]:.2f}.\n{tail.strip()}",
        f"{_source(r)} Log-log OLS fits.\nThe formula at fixed liquidity predicts σ²; "
        "a flatter measured slope fits LPs pulling liquidity on volatile days.",
    )
    return fig


def cumulative(r: Results) -> Figure:
    p = pal()
    d = r.daily.sort("day")
    s = r.summary["lp"]["daily"]
    fig, ax = new_figure(right=0.73)
    x = d["day"].to_list()
    lp = np.cumsum(d["fees_usd"].to_numpy())
    total = np.cumsum((d["fees_usd"] + d["protocol_fee_usd"]).to_numpy())
    lvr = np.cumsum(d["lvr_0"].to_numpy())
    ax.fill_between(x, lp, lvr, where=lvr >= lp, color=p.lvr, alpha=0.14, lw=0)
    ax.plot(x, lvr, color=p.lvr, lw=2.4)
    ax.plot(x, lp, color=p.fees, lw=2.4)
    ax.plot(x, total, color=p.fees, lw=1.3, ls=(0, (4, 3)))
    for y, text, c in (
        (lvr[-1], f"LVR  {usd(lvr[-1])}", p.lvr),
        (lp[-1], f"LP fees  {usd(lp[-1])}", p.fees),
        (total[-1], f"Total fees  {usd(total[-1])}", p.fees),
    ):
        ax.annotate(
            text,
            (x[-1], y),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            color=c,
            fontsize=9.5,
            fontweight="bold",
            annotation_clip=False,
        )
    worst = int(np.argmax(d["lvr_0"].to_numpy()))
    ax.annotate(
        f"{x[worst]:%d %b}: {usd(float(d['lvr_0'][worst]))} of LVR in one day",
        (x[worst], lvr[worst]),
        xytext=(-12, 26),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=p.muted,
        arrowprops={"arrowstyle": "-", "color": p.muted, "lw": 0.8},
    )
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.xaxis.set_major_formatter(DateFormatter("%d %b"))  # type: ignore[no-untyped-call]
    ax.set_ylabel("Cumulative USD since the window start")
    frame(
        fig,
        "Over the window, LVR pulled ahead of LP fees"
        if lvr[-1] > lp[-1]
        else "Cumulative LP fees and LVR over the window",
        f"LP fees − LVR: {usd(s['fees_minus_lvr_usd'])} (95% interval "
        f"{usd(s['fees_minus_lvr_ci_lo_usd'])} to {usd(s['fees_minus_lvr_ci_hi_usd'])}). "
        + (
            "Before the protocol's cut, total fees fell short by only "
            f"{usd(-s['total_fees_minus_lvr_usd'])} "
            if s["total_fees_minus_lvr_usd"] < 0
            else "Before the protocol's cut, total fees exceeded LVR by "
            f"{usd(s['total_fees_minus_lvr_usd'])} "
        )
        + f"(interval {usd(s['total_fees_minus_lvr_ci_lo_usd'])} to "
        f"{usd(s['total_fees_minus_lvr_ci_hi_usd'])}), and LVR beat LP fees on "
        f"{s['days_lvr_above_lp_fees']} of {s['days']} days.",
        f"{_source(r)} Intervals: bootstrap over days ({s.get('bootstrap', '1,000 resamples')}).",
    )
    return fig


def measured_vs_theory(r: Results) -> Figure:
    p = pal()
    d = r.daily.with_columns(
        gross=pl.col("lvr_0_searcher") - pl.col("fees_searcher") - pl.col("protocol_fees_searcher")
    )
    fig, (a, b) = new_figure(1, 2, top=0.76, bottom=0.15, wspace=0.25)
    ratios = []
    for ax, xcol, ycol, title, c in (
        (a, "theory_1s", "lvr_0_searcher", "(a) Before fees: searcher LVR", p.lvr),
        (b, "theory_arb", "gross", "(b) After fees: searchers' gross", p.jit),
    ):
        xv, yv = d[xcol].to_numpy() / 1e3, d[ycol].to_numpy() / 1e3
        hi = max(float(np.nanmax(xv)), float(np.nanmax(yv)), 1e-9) * 1.05
        lo = min(0.0, float(np.nanmin(yv)))
        ax.plot([lo, hi], [lo, hi], color=p.muted, lw=1, ls=(0, (3, 3)))
        ax.scatter(xv, yv, s=30, color=c, alpha=0.6, edgecolor=p.background, lw=0.5)
        den = float(d[xcol].sum())
        ratio = float(d[ycol].sum()) / den if den else float("nan")
        ratios.append(ratio)
        ax.text(
            0.04,
            0.95,
            f"measured / theory = {ratio:.2f}×\nover the window",
            transform=ax.transAxes,
            va="top",
            fontsize=9.5,
            color=c,
        )
        ax.text(hi, hi, " 45°", color=p.muted, fontsize=8.5, va="bottom")
        ax.set_title(title, loc="left", fontsize=10.5, color=p.ink)
        ax.set_xlabel("Theory, USD thousands per day")
        ax.set_ylabel("Measured, USD thousands per day")
        ax.grid(True, axis="both")
    frame(
        fig,
        "Measured arbitrage runs above the LVR formula, before and after fees"
        if min(ratios) > 1
        else "Measured arbitrage against the LVR formula",
        f"Each dot is one day. Before fees, measured LVR on searcher swaps is {ratios[0]:.2f}× "
        f"the formula; after LP and protocol fees, searchers' gross is {ratios[1]:.2f}× the "
        "formula's expected arbitrage profit.",
        "Theory: Milionis et al. (2022) with 1 s Binance returns; P_trade from Milionis, "
        "Moallemi, Roughgarden (2023), 0.05% fee and 12 s blocks.",
    )
    return fig
