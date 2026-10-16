"""Chapter 'What is LVR?': the concept diagram (figure 1), a real stale-pool episode (figure 2)
and its animation."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from uniswap_lp_economics.config import BLOCK_TIME_S, US
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import (
    frame,
    new_figure,
    no_data,
    pal,
    panel_header,
    theme,
    usd,
)

GIF_NAME = "02_stale_pool_episode.gif"
# where an arbitrage label may sit, in points from its dot, in order of preference
LABEL_OFFSETS = (
    (10, -8),
    (-10, -8),
    (10, 8),
    (-10, 8),
    (14, -24),
    (-14, -24),
    (14, 24),
    (-14, 24),
    (24, -40),
    (-24, -40),
    (24, 40),
    (-24, 40),
)
CONCEPT_STEPS = (
    ("Binance moves", "Between two blocks, the price on Binance changes."),
    ("The pool is stale", "Uniswap's price can only change when the next block lands."),
    (
        "An arbitrageur trades",
        "In that block, a bot buys ETH from the pool at the old, cheaper price.",
    ),
    ("The LP pays the gap", "The pool sold below Binance's price: that difference is LVR."),
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
        if i == 3:  # only the gap at the trade is the LP's loss
            ax.fill_between([11.5, 12.5], 100.0, cex[-1], color=p.lvr, alpha=0.30, lw=0)
            ax.text(
                11.2,
                (100.0 + cex[-1]) / 2,
                "LVR",
                ha="right",
                va="center",
                fontsize=9.5,
                fontweight="bold",
                color=p.lvr,
            )
        panel_header(ax, i + 1, head, text)
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
    ranked = [int(i) for i in np.argsort(-np.where(arb, lvr, -np.inf))[:4] if arb[i]]
    _label_arbs(ax, [(bt[i], pool[i], f"arb takes {usd(lvr[i])}") for i in ranked], ct, cp)


def _line_points(ax: Axes, x: np.ndarray, y: np.ndarray, step_px: float = 1.5) -> np.ndarray:
    """Display-space points along a polyline, at most step_px apart."""
    xy = ax.transData.transform(np.column_stack([x, y]))
    if len(xy) < 2:
        return xy
    out = [xy[:1]]
    for a, b in zip(xy[:-1], xy[1:], strict=True):
        k = max(1, int(np.ceil(np.hypot(*(b - a)) / step_px)))
        out.append(a + (b - a) * (np.arange(1, k + 1) / k)[:, None])
    return np.concatenate(out)


def _label_arbs(
    ax: Axes, labels: list[tuple[float, float, str]], ct: np.ndarray, cp: np.ndarray
) -> None:
    """Label the largest arbitrages, each at the first nearby spot that keeps it off the Binance
    line, the other labels and the panel's text."""
    p = pal()
    renderer = ax.figure.canvas.get_renderer()  # type: ignore[attr-defined]
    line = _line_points(ax, ct, cp)
    frame_box = ax.get_window_extent(renderer)
    taken = [t.get_window_extent(renderer).padded(3.0) for t in ax.texts]
    for x, y, text in labels:
        best: tuple[int, Any] | None = None
        for dx, dy in LABEL_OFFSETS:
            ann = ax.annotate(
                text,
                (x, y),
                xytext=(dx, dy),
                textcoords="offset points",
                fontsize=9.5,
                color=p.lvr,
                fontweight="bold",
                ha="left" if dx > 0 else "right",
                va="top" if dy < 0 else "bottom",
            )
            box = ann.get_window_extent(renderer).padded(3.0)
            clash = int(box.count_contains(line)) + sum(box.overlaps(t) for t in taken)
            clash += (
                0
                if frame_box.contains(box.x0, box.y0) and frame_box.contains(box.x1, box.y1)
                else 10_000
            )
            if best is None or clash < best[0]:
                if best is not None:
                    best[1].remove()
                best = (clash, ann)
            else:
                ann.remove()
            if clash == 0:
                break
        if best is not None:
            taken.append(best[1].get_window_extent(renderer).padded(3.0))


def _subtitle(b: pl.DataFrame) -> str:
    day = datetime.fromtimestamp(int(b["ts_us"][0]) / US, tz=UTC).date()
    minutes = b.height * BLOCK_TIME_S / 60
    total = float(b["lvr_0_usd"].sum())
    return (
        f"{day}: Binance moves first; the pool's price changes only when a block lands, and the "
        f"arbitrage in each block trades it back to Binance. Over these {b.height} blocks "
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
