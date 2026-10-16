"""Chapter 'Who pays?': every position (figure 9), P&L by group in USD per $10,000 per month
(figure 10) and lifetime vs holding (figure 12)."""

import textwrap
from typing import Any

import polars as pl
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from uniswap_lp_economics.lp.pnl import WIDTH_BUCKETS
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import (
    USD_FMT,
    frame,
    new_figure,
    no_data,
    pal,
    panel_header,
    pct,
    per_10k_month,
    usd,
)

MIN_VALUE_USD = 100.0
SYMLOG_LINTHRESH_USD = 10.0  # figure 9's P&L axis is linear within ± this
LP_NAMES = {
    "jit": "JIT (same block)",
    "nft_wallet": "Wallet NFT",
    "lp_vault": "Vault",
    "nft_contract": "Contract NFT",
    "direct_other": "Other direct",
}
LIFE_NAMES = {
    "<1d": "Under a day",
    "1-7d": "1–7 days",
    "7-30d": "7–30 days",
    "30-180d": "30–180 days",
    ">=180d": "180 days or more",
}
WIDTH_NAMES = {
    "<50": "Under 50 bp",
    "50-200": "50–200 bp",
    "200-1000": "200–1,000 bp",
    "1000-5000": "1,000–5,000 bp",
    ">=5000": "5,000 bp or more",
}
PNL_SOURCE = (
    "P&L = fees − LVR (0 s) − gas − direct builder payments, against a portfolio that "
    "rebalances at Binance's last trade."
)


def every_position(r: Results) -> Figure:
    p = pal()
    pos_all = r.positions
    pos = pos_all.filter(pl.col("twv_usd") >= MIN_VALUE_USD)
    hidden = pos_all.height - pos.height
    fig, ax = new_figure(left=0.10, right=0.76)
    colors = {"jit": p.jit, "nft_wallet": p.fees}
    for t in ("nft_contract", "direct_other", "lp_vault", "nft_wallet", "jit"):
        g = pos.filter(pl.col("lp_type") == t)
        if g.height:
            ax.scatter(
                g["twv_usd"],
                g["pnl_rebal_usd"],
                s=13 if t == "jit" else 9,
                color=colors.get(t, p.other),
                alpha=0.65 if t == "jit" else 0.35,
                lw=0,
                zorder=3 if t == "jit" else 2,
                rasterized=True,  # thousands of dots: a bitmap keeps the SVG small
            )
    if pos.height == 0:
        no_data(ax, f"no position worth ${MIN_VALUE_USD:.0f} or more")
    else:
        ax.set_xscale("log")
        ax.set_yscale("symlog", linthresh=SYMLOG_LINTHRESH_USD)
        ax.set_xlim(MIN_VALUE_USD, float(pos["twv_usd"].cast(pl.Float64).max()) * 1.6)  # type: ignore[arg-type]
    ax.axhline(0, color=p.ink, lw=0.9, zorder=1)
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.xaxis.set_major_formatter(USD_FMT)
    ax.grid(True, axis="both")
    slots = (("jit", 0.86, p.jit), ("nft_wallet", 0.60, p.fees), ("lp_vault", 0.34, p.muted))
    for t, y, c in slots:
        g = pos_all.filter(pl.col("lp_type") == t)
        if g.height:
            share = float((g["pnl_rebal_usd"] > 0).mean())  # type: ignore[arg-type]
            ax.text(
                1.015,
                y,
                f"{LP_NAMES[t]}\n{g.height:,} positions\n"
                f"{usd(float(g['pnl_rebal_usd'].sum()))} in total\n{pct(share)} made money",
                transform=ax.transAxes,
                fontsize=9.5,
                color=c,
                va="center",
                fontweight="bold",
            )
    ax.text(
        1.015,
        0.12,
        "Grey: vaults, contract\nNFTs, other direct",
        transform=ax.transAxes,
        fontsize=9,
        color=p.muted,
        va="center",
    )
    ax.set_xlabel("Average position value while open (log scale)")
    ax.set_ylabel("P&L vs rebalancing at Binance (symlog)")
    lose = float((pos_all["pnl_rebal_usd"] < 0).mean()) if pos_all.height else 0.0  # type: ignore[arg-type]
    plural = "position" if hidden == 1 else "positions"
    jit_all = pos_all.filter(pl.col("lp_type") == "jit")
    jit_win = (
        float((jit_all["pnl_rebal_usd"] > 0).mean())  # type: ignore[arg-type]
        if jit_all.height
        else -1.0
    )
    frame(
        fig,
        f"{pct(lose)} of LPs lost money against rebalancing"
        + ("; JIT is a coin flip" if 0.35 <= jit_win <= 0.65 else ""),
        f"Each dot is one of the {pos_all.height:,} positions active in the window. {pct(lose)} "
        "lost money after fees, gas and builder payments; the losses scale with size. JIT "
        "positions are large but live for a single block.",
        f"{PNL_SOURCE} Symlog axis: linear within ±{usd(SYMLOG_LINTHRESH_USD)}.\n"
        f"{hidden:,} {plural} worth under "
        f"${MIN_VALUE_USD:.0f} not drawn; the group totals on the right include them.",
    )
    return fig


def _tick(name: str) -> str:
    """A category label wrapped to sit flat under its dot; a number keeps its unit, and a long
    range breaks after its dash ("1,000\u2013" over "5,000 bp")."""
    wrapped = textwrap.fill(name.replace(" bp", "\u00a0bp"), 10, break_long_words=False)
    lines = [
        line.replace("\u2013", "\u2013\n", 1) if len(line) > 10 and "\u2013" in line else line
        for line in wrapped.split("\n")
    ]
    return "\n".join(lines).replace("\u00a0", " ")


def _dots(ax: Axes, rows: list[dict[str, Any]], names: dict[str, str], color: str) -> None:
    p = pal()
    for i, row in enumerate(rows):
        v = per_10k_month(row["bp_per_day"])
        lo, hi = per_10k_month(row["ci_lo_bp"]), per_10k_month(row["ci_hi_bp"])
        ax.plot([i, i], [lo, hi], color=color, lw=7, alpha=0.16, solid_capstyle="round")
        ax.plot([i, i], [lo, hi], color=color, lw=1.6, alpha=0.6)
        spans = lo <= 0 <= hi
        ax.scatter(
            [i],
            [v],
            s=70,
            zorder=3,
            facecolor=p.background if spans else color,
            edgecolor=color,
            lw=2,
        )
        ax.annotate(
            usd(v),
            (i, v),
            xytext=(7, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=p.ink,
        )
    ax.axhline(0, color=p.muted, lw=0.8)
    ax.set_xticks(
        range(len(rows)),
        [_tick(names.get(row["group"], row["group"])) for row in rows],
        fontsize=8.5,
    )
    ax.set_xlim(-0.6, max(len(rows), 1) - 0.4)
    ax.yaxis.set_major_formatter(USD_FMT)


def pnl_by_group(r: Results) -> Figure:
    p = pal()
    g = r.groups
    types = [
        row
        for t in ("nft_wallet", "lp_vault", "nft_contract", "direct_other")
        for row in g.filter((pl.col("grouping") == "lp_type") & (pl.col("group") == t)).to_dicts()
    ]
    jit = g.filter((pl.col("grouping") == "lp_type") & (pl.col("group") == "jit")).to_dicts()
    widths = [
        row
        for w in WIDTH_BUCKETS
        for row in g.filter(
            (pl.col("grouping") == "width_bucket") & (pl.col("group") == w)
        ).to_dicts()
    ]
    fig, (a, j, w) = new_figure(1, 3, top=0.74, bottom=0.22, wspace=0.52, width_ratios=[4, 1.5, 5])
    for ax, rows, names, color, header in (
        (a, types, LP_NAMES, p.fees, (1, "By LP type", "How the position is held")),
        (j, jit, LP_NAMES, p.jit, (2, "JIT", "Own scale: single-block positions")),
        (w, widths, WIDTH_NAMES, p.other, (3, "By range width", "Width of the price range")),
    ):
        if rows:
            _dots(ax, rows, names, color)
        else:
            no_data(ax, "none")
        panel_header(ax, *header)
    a.set_ylabel("USD per $10,000 of position value per month")
    wallet = next((row for row in types if row["group"] == "nft_wallet"), None)
    lead = (
        f"Wallet NFTs, which earned most of the fees: {usd(per_10k_month(wallet['bp_per_day']))} "
        f"per month ({usd(per_10k_month(wallet['ci_lo_bp']))} to "
        f"{usd(per_10k_month(wallet['ci_hi_bp']))})."
        if wallet
        else ""
    )
    frame(
        fig,
        "Every LP type except JIT lost money, and JIT's result could be luck"
        if all(row["ci_hi_bp"] < 0 for row in types)
        and all(row["ci_lo_bp"] <= 0 <= row["ci_hi_bp"] for row in jit)
        else "P&L against rebalancing by LP type and range width",
        "P&L against rebalancing at Binance, in USD per $10,000 of time-weighted position value "
        f"per 30 days. {lead}",
        f"{PNL_SOURCE} 95% intervals: bootstrap over positions. Hollow dot: the interval spans "
        "zero.",
    )
    return fig


def lifetime(r: Results) -> Figure:
    p = pal()
    lp = r.summary["lp"]
    fig, axes = new_figure(1, 2, left=0.13, top=0.76, bottom=0.14, wspace=0.55)
    for ax, rows, key, names, header in (
        (
            axes[0],
            lp["lifetime_by_life"],
            "life_bucket",
            LIFE_NAMES,
            (1, "By how long it lived", "Dashed line: half of the positions beat holding"),
        ),
        (
            axes[1],
            lp["lifetime_by_width"],
            "width_bucket",
            WIDTH_NAMES,
            (2, "By range width", "Width of the position's price range"),
        ),
    ):
        panel_header(ax, *header)
        if not rows:
            no_data(ax)
            continue
        ys = list(range(len(rows)))
        vals = [float(row["share_beat_hold"]) for row in rows]
        ax.axvline(0.5, color=p.muted, lw=1, ls=(0, (3, 3)))
        ax.hlines(ys, 0.5, vals, color=p.faint, lw=2)
        ax.scatter(vals, ys, s=80, zorder=3, color=[p.fees if v >= 0.5 else p.lvr for v in vals])
        for y, v, row in zip(ys, vals, rows, strict=True):
            ax.text(
                v + (0.03 if v >= 0.5 else -0.03),
                y,
                f"{pct(v)}  ({row['positions']:,})",
                va="center",
                ha="left" if v >= 0.5 else "right",
                fontsize=9,
                color=p.ink,
            )
        ax.set_yticks(ys, [names.get(row[key], row[key]) for row in rows])
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v)))
        ax.grid(True, axis="x")
        ax.grid(False, axis="y")
    o = lp["lifetime"]
    old = next((row for row in lp["lifetime_by_life"] if row["life_bucket"] == ">=180d"), None)
    tail = f"; {pct(old['share_beat_hold'])} of those that lived 180 days or more" if old else ""
    frame(
        fig,
        "Over their whole life, about half of LPs beat simply holding"
        if 0.4 <= o["share_beat_hold"] <= 0.6
        else f"Over their whole life, {pct(o['share_beat_hold'])} of LPs beat simply holding",
        f"Share of window-active positions whose lifetime result beat holding the deposited "
        f"tokens: {pct(o['share_beat_hold'])} overall{tail}. Numbers in brackets: positions.",
        "Gas and builder payments inside the window are charged; costs before it are not "
        "observed. Shares count positions, not dollars, and depend on each position's price path.",
    )
    return fig
