"""Chapter 'What is LVR?': the concept diagram (figure 1), a real stale-pool episode (figure 2)
and its animation."""

from datetime import UTC, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from uniswap_lp_economics.config import BLOCK_TIME_S, US
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import frame, new_figure, no_data, pal, theme, usd

GIF_NAME = "02_stale_pool_episode.gif"
CONCEPT_STEPS = (
    ("1  Binance moves", "Between two blocks, the price\non Binance changes."),
    ("2  The pool is stale", "Uniswap's price can only change\nwhen the next block lands."),
    (
        "3  An arbitrageur trades",
        "In that block, a bot buys ETH from\nthe pool at the old, cheaper price.",
    ),
    ("4  The LP pays the gap", "The pool sold below Binance's price:\nthat difference is LVR."),
)
EPISODE_TITLE = "LVR is the price of a stale pool"
EPISODE_SOURCE = (
    "Pool price after each block, from the pool's sqrtPriceX96; Binance ETHUSDC, last trade each "
    "second; LVR (0 s) per block, summed over the block's swap steps."
)


def concept(r: Results) -> Figure:
    p = pal()
    fig, axes = new_figure(1, 4, sharey=True, top=0.74, bottom=0.24, wspace=0.12)
    t = np.linspace(0, 12, 121)
    cex = 100 + 4 / (1 + np.exp(-(t - 5)))
    for i, (ax, (head, text)) in enumerate(zip(axes, CONCEPT_STEPS, strict=True)):
        ax.plot(t, cex, color=p.binance, lw=1.6)
        if i >= 1:
            ax.plot(t, np.full_like(t, 100.0), color=p.fees, lw=2.6)
        if i == 2 or i == 3:
            ax.plot([12, 12], [100, cex[-1]], color=p.fees, lw=2.6)
            ax.scatter([12], [cex[-1]], s=70, color=p.lvr, zorder=5)
        if i == 3:
            ax.fill_between(t, 100.0, cex, color=p.lvr, alpha=0.22, lw=0)
        ax.set_title(head, loc="left", fontsize=11.5, fontweight="bold", color=p.ink)
        ax.text(0.0, -0.06, text, transform=ax.transAxes, va="top", fontsize=9.5, color=p.muted)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        ax.set_xlim(0, 13)
        ax.set_ylim(99.3, 104.8)
    axes[0].text(0.3, 104.3, "Binance", color=p.binance, fontsize=9.5)
    axes[1].text(0.3, 100.25, "Uniswap pool", color=p.fees, fontsize=9.5)
    frame(
        fig,
        "LVR: what an LP loses because the pool's price is always a step behind",
        "Schematic, not data. Every price move on Binance opens a gap; the next block's "
        "arbitrage closes it at the LP's expense.",
        "LVR (loss-versus-rebalancing): Milionis, Moallemi, Roughgarden and Zhang (2022). "
        "Illustrative numbers.",
    )
    return fig


def _draw_episode(ax: Axes, b: pl.DataFrame, c: pl.DataFrame, n: int) -> None:
    """The first n blocks of the episode; the axis limits always cover the whole window."""
    p = pal()
    t0 = int(b["ts_us"][0])
    bt_all = (b["ts_us"].to_numpy() - t0) / US
    pool_all = b["pool_price"].to_numpy().astype(float)
    ct_all = (c["ts_us"].to_numpy() - t0) / US
    cp_all = c["price"].to_numpy().astype(float)
    bt, pool = bt_all[:n], pool_all[:n]
    t_end = bt[-1] + BLOCK_TIME_S
    keep = ct_all < t_end
    ct, cp = ct_all[keep], cp_all[keep]
    if len(ct):
        idx = np.clip(np.searchsorted(bt, ct, side="right") - 1, 0, n - 1)
        on = ct >= bt[0]
        ax.fill_between(ct[on], cp[on], pool[idx][on], color=p.lvr, alpha=0.18, lw=0)
        ax.plot(ct, cp, color=p.binance, lw=1.1)
    ax.step(np.append(bt, t_end), np.append(pool, pool[-1]), where="post", color=p.fees, lw=2.4)
    lvr = b["lvr_0_usd"].to_numpy().astype(float)[:n]
    arb = b["has_searcher"].to_numpy().astype(bool)[:n] & (lvr > 0)
    ax.scatter(
        bt[arb],
        pool[arb],
        s=28 + lvr[arb] / 40,
        color=p.lvr,
        edgecolor=p.background,
        lw=0.8,
        zorder=5,
    )
    ranked = [int(i) for i in np.argsort(-np.where(arb, lvr, -np.inf))[:4] if arb[i]]
    for rank, i in enumerate(ranked):
        ax.annotate(
            f"arb takes {usd(lvr[i])}",
            (bt[i], pool[i]),
            xytext=(-14, 14) if rank == 0 else (10, -16),
            textcoords="offset points",
            fontsize=9.5,
            color=p.lvr,
            fontweight="bold",
            ha="right" if rank == 0 else "left",
        )
    lo = min(pool_all.min(), cp_all.min() if len(cp_all) else pool_all.min())
    hi = max(pool_all.max(), cp_all.max() if len(cp_all) else pool_all.max())
    pad = (hi - lo) * 0.06 or 1.0
    ax.set_xlim(0, bt_all[-1] + BLOCK_TIME_S)
    ax.set_ylim(lo - pad, hi + pad)
    ax.text(
        0.01,
        0.97,
        "Binance (each second)",
        transform=ax.transAxes,
        color=p.binance,
        fontsize=9.5,
        va="top",
    )
    ax.text(
        0.01,
        0.92,
        "Uniswap pool (per block)",
        transform=ax.transAxes,
        color=p.fees,
        fontsize=9.5,
        va="top",
    )
    ax.text(
        0.99,
        0.04,
        "shaded gap = how stale the pool is;\neach block's arbitrage closes it,\n"
        "and the LPs pay the difference (LVR)",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9.5,
        color=p.muted,
    )
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.set_xlabel("Seconds (12 s per block)")
    ax.set_ylabel("ETH price (USD)")


def _subtitle(b: pl.DataFrame) -> str:
    day = datetime.fromtimestamp(int(b["ts_us"][0]) / US, tz=UTC).date()
    minutes = b.height * BLOCK_TIME_S / 60
    total = float(b["lvr_0_usd"].sum())
    return (
        f"{day}: Binance moves first; the pool's price changes only when a block lands, and the "
        f"arbitrage in each block\ntrades it back to Binance. Over these {b.height} blocks "
        f"({minutes:.0f} min) LPs lost {usd(total)} to arbitrage."
    )


def episode(r: Results) -> Figure:
    b, c = r.episode_blocks.sort("ts_us"), r.episode_cex.sort("ts_us")
    fig, ax = new_figure()
    if b.height == 0:
        no_data(ax, "no episode in the results")
        frame(fig, EPISODE_TITLE, "No episode data.", EPISODE_SOURCE)
        return fig
    _draw_episode(ax, b, c, b.height)
    frame(fig, EPISODE_TITLE, _subtitle(b), EPISODE_SOURCE)
    return fig


def episode_gif(r: Results, out_dir: Path) -> list[Path]:
    """The episode drawn block by block (light mode only, spec section 7)."""
    b, c = r.episode_blocks.sort("ts_us"), r.episode_cex.sort("ts_us")
    if b.height == 0:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / GIF_NAME
    with theme("light"):
        fig, ax = new_figure()
        frame(fig, EPISODE_TITLE, _subtitle(b), EPISODE_SOURCE)

        def draw(k: int) -> None:
            ax.clear()
            _draw_episode(ax, b, c, k + 1)

        anim = FuncAnimation(fig, draw, frames=b.height, interval=600)
        anim.save(path, writer=PillowWriter(fps=2), dpi=80)
        plt.close(fig)
    return [path]
