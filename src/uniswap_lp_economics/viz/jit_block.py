"""Figure 11: one real JIT block, event by event, with the position's totals."""

from typing import Any

import numpy as np
import polars as pl
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import frame, new_figure, no_data, pal, usd

MAX_CONTEXT = 1  # other events shown before the first and after the last JIT/operator event
SOURCE = (
    "Operator = the JIT position's own transactions. Markout = the swap's result against "
    "Binance at 0 s. Position totals from positions.csv; operator, all in = the position's P&L "
    "plus its own swaps' markout."
)


def _caption(row: dict[str, Any]) -> str:
    if row["event"] == "swap":
        who = "Operator's swap" if row["role"] == "operator" else "Swap"
        parts = [who, usd(row["notional_usd"] or 0.0)]
        if row["markout_usd_0"] is not None:
            parts.append(f"markout {usd(row['markout_usd_0'])}")
        if row["role"] == "other" and row["fee_usd"] is not None:
            parts.append(f"fee {usd(row['fee_usd'])}")
        return "\n".join(parts)
    value = abs(row["amount_usdc"]) + abs(row["amount_eth"]) * row["pool_price_after"]
    if row["event"] == "mint":
        return f"JIT adds\nliquidity\n{usd(value)}"
    if row["event"] == "burn":
        return f"JIT removes\nliquidity\n{usd(value)}"
    return str(row["event"]).capitalize()


def jit_block(r: Results) -> Figure:
    p = pal()
    t = r.jit_block.sort("log_index")
    fig, ax = new_figure(right=0.75, top=0.76, bottom=0.30)
    if t.height == 0:
        no_data(ax, "no JIT position in the window")
        frame(fig, "Inside a JIT block", "No JIT position in the window.", SOURCE)
        return fig
    own_markout = float(
        t.filter(pl.col("role") == "operator")["markout_usd_0"].fill_null(0.0).sum()
    )
    roles = t["role"].to_list()
    keyed = [i for i, role in enumerate(roles) if role != "other"]
    lo, hi = max(keyed[0] - MAX_CONTEXT, 0), min(keyed[-1] + MAX_CONTEXT, t.height - 1)
    t = t.slice(lo, hi - lo + 1)
    rows = t.to_dicts()
    x = np.arange(len(rows))
    price = t["pool_price_after"].to_numpy().astype(float)
    start = float(rows[0]["pool_price_before"])
    # The price changes at each event: from the price before the first shown event (for the full
    # block, its start) to the price after each one.
    ax.step(
        np.concatenate([[-0.6], x, [len(rows) - 0.4]]),
        np.concatenate([[start], price, [price[-1]]]),
        where="post",
        color=p.fees,
        lw=2.2,
    )
    colors = {"operator": p.lvr, "jit": p.jit, "other": p.other}
    for i, row in enumerate(rows):
        ax.scatter(
            [i], [price[i]], s=90, color=colors[row["role"]], zorder=4, edgecolor=p.background, lw=1
        )
        ax.annotate(
            _caption(row),
            (i, 0),
            xycoords=("data", "axes fraction"),
            xytext=(0, -10),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=8.5,
            color=colors[row["role"]],
        )
    ax.set_xticks([])
    ax.set_xlim(-0.6, len(rows) - 0.4)
    lo_p, hi_p = min(float(price.min()), start), max(float(price.max()), start)
    pad = max((hi_p - lo_p) * 0.3, 1.0)
    ax.set_ylim(lo_p - pad, hi_p + pad)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.set_ylabel("Pool price after the event")
    pid, block = rows[0]["position_id"], int(rows[0]["block_number"])
    if bool(rows[0]["full_pattern"]):
        title = "Inside one JIT block: the operator's own swaps bracket its liquidity"
        sub = (
            f"Block {block:,}, pool events in order. The JIT operator swaps before adding "
            "liquidity and after removing it; the swap in between is the one the JIT "
            "position serves."
        )
    else:
        title = "Inside the most profitable JIT block"
        sub = (
            f"Block {block:,}, pool events in order. No JIT position in the window had its "
            "own swaps on both sides of its liquidity; this is the most profitable one."
        )
    frame(fig, title, sub, SOURCE)  # first, so fig.texts[0] is the title
    pos = r.positions.filter(pl.col("position_id") == pid)
    if pos.height:
        q = pos.row(0, named=True)
        lines = [
            ("Fees earned", q.get("fee_usd"), p.fees),
            ("LVR (negative = gain)", q.get("lvr_0"), p.lvr),
            ("Gas", q.get("gas_usd"), p.muted),
            ("Builder payments", q.get("direct_usd"), p.muted),
            ("P&L vs rebalancing", q.get("pnl_rebal_usd"), p.ink),
            ("Operator's own swaps", own_markout, p.lvr),
            (
                "Operator, all in",
                None if q.get("pnl_rebal_usd") is None else q["pnl_rebal_usd"] + own_markout,
                p.ink,
            ),
        ]
        y = 0.70
        fig.text(0.78, y + 0.06, "This JIT position", fontsize=10.5, fontweight="bold", color=p.ink)
        for label, v, c in lines:
            fig.text(0.78, y, label, fontsize=9.5, color=p.muted)
            fig.text(
                0.985,
                y,
                usd(float(v)) if v is not None else "n/a",
                fontsize=9.5,
                color=c,
                ha="right",
                fontweight="bold",
            )
            y -= 0.05
    return fig
