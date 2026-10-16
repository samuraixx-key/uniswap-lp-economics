"""Chapter 'Do arbitrage bots keep the edge?' (figure 8): available -> kept waterfall and each
top bot's gross vs kept (sub-project 2)."""

import polars as pl
from matplotlib.figure import Figure

from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import USD_FMT, frame, new_figure, no_data, pal, usd

# (summary.arbitrage key, label, kind): "total" bars stand on zero, "minus" bars float down
WATERFALL = (
    ("available_usd", "Available", "total"),
    ("captured_searchers_usd", "Captured\n(searchers)", "total"),
    ("top_bot_single_pool_gross_usd", "Top bots'\ngross", "total"),
    ("gas_burned_usd", "Base\nfee", "minus"),
    ("priority_fee_usd", "Priority\nfee", "minus"),
    ("coinbase_usd", "Direct\npayment", "minus"),
    ("kept_usd", "Kept\n(upper\nbound)", "total"),
)


def bots_keep(r: Results) -> Figure:
    p = pal()
    w = r.summary["arbitrage"]
    fig, (a, b) = new_figure(1, 2, top=0.76, bottom=0.20, wspace=0.42, width_ratios=[1.6, 1.0])
    level = 0.0
    for i, (key, _label, kind) in enumerate(WATERFALL):
        v = float(w.get(key) or 0.0)
        if kind == "total":
            color = (
                p.lvr if key == "kept_usd" and v < 0 else p.fees if key == "kept_usd" else p.other
            )
            a.bar(i, v, color=color, width=0.62)
            level = v
            a.annotate(
                usd(v),
                (i, v),
                xytext=(0, 6 if v >= 0 else -6),
                textcoords="offset points",
                ha="center",
                va="bottom" if v >= 0 else "top",
                fontsize=9,
                color=p.ink,
            )
        else:
            a.bar(
                i,
                -v,
                bottom=level,
                color=p.builder if key != "gas_burned_usd" else p.faint,
                width=0.62,
            )
            a.text(i, level, f"−{usd(v)}", ha="center", va="bottom", fontsize=9, color=p.muted)
            level -= v
    a.margins(y=0.18)
    a.axhline(0, color=p.muted, lw=0.8)
    a.set_xticks(range(len(WATERFALL)), [label for _, label, _ in WATERFALL], fontsize=8.5)
    a.yaxis.set_major_formatter(USD_FMT)
    a.set_title("(a) Available → captured → kept", loc="left", fontsize=10.5, color=p.ink)
    bots = r.bot_profit.filter(pl.col("sender") != "TOTAL").sort("gross_usd")
    if bots.height:
        y = list(range(bots.height))
        b.barh(y, bots["gross_usd"].to_list(), color=p.other, alpha=0.45, height=0.6)
        kept = bots["kept_usd"].to_list()
        b.scatter(kept, y, s=60, zorder=3, color=[p.lvr if k < 0 else p.fees for k in kept])
        b.axvline(0, color=p.muted, lw=0.8)
        b.set_yticks(y, [f"{s[:6]}…{s[-4:]}" for s in bots["sender"].to_list()], fontsize=8.5)
        b.xaxis.set_major_formatter(USD_FMT)
        b.grid(True, axis="x")
        b.grid(False, axis="y")
        b.text(
            0.98,
            0.02,
            "bar: gross at 0 s\ndot: kept",
            transform=b.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            color=p.muted,
        )
    else:
        no_data(b)
    b.set_title("(b) Per top bot", loc="left", fontsize=10.5, color=p.ink)
    g, k = float(w.get("top_bot_single_pool_gross_usd") or 0), float(w.get("kept_usd") or 0)
    paid = float(w.get("priority_fee_usd") or 0) + float(w.get("coinbase_usd") or 0)
    frame(
        fig,
        "Arbitrage bots hand most of their edge to block builders"
        if paid > g / 2
        else "What arbitrage bots keep after gas and builder payments",
        f"Top bots' single-pool gross at 0 s: {usd(g)}. After the base fee, priority fees and "
        f"direct payments to the block's fee recipient, they kept {usd(k)} (an upper bound).",
        "Sub-project 2. Available = arbitrage available at block starts before gas and Binance "
        "fees. Kept misses payments outside the transaction.",
    )
    return fig
