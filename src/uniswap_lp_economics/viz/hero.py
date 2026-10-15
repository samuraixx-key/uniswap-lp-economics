"""The hero (README top): where the LVR on searcher swaps went, as a Sankey, with the uncertain
proposer/builder split hatched; also the 1280×640 social card."""

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path as MplPath

from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import CANVAS, Palette, frame, pal, pct, theme, usd

Node = tuple[str, float, str]
CARD_NAME = "00_hero.png"
DEST_KEYS = (
    ("fees_on_searcher_swaps_usd", "LP fees", "fees"),
    ("protocol_fees_on_searcher_swaps_usd", "Protocol fees", "protocol"),
    ("multi_pool_gross_usd", "Multi-pool arbitrage (not split)", "other"),
    ("gas_burned_usd", "Gas burned", "faint"),
    ("builder_margin_usd", "Block builders", "builder"),
    ("proposer_usd", "Proposers", "proposer"),
)
X_LEFT, X_RIGHT, NODE_W = 0.0, 0.80, 0.03


def flows(dest: dict[str, Any], p: Palette) -> tuple[list[Node], list[Node]]:
    """Sources (LVR on searcher swaps, plus any negative outflow) and destinations (the
    non-negative outflows, plus searchers' kept when positive). Raises when they do not balance."""
    lvr = float(dest["lvr_on_searcher_swaps_usd"])
    sources: list[Node] = [("LVR on searcher swaps", lvr, p.lvr)]
    dests: list[Node] = []
    for key, label, color in DEST_KEYS:
        v = float(dest[key])
        if v >= 0:
            dests.append((label, v, getattr(p, color)))
        else:
            sources.append((f"{label} (negative)", -v, getattr(p, color)))
    kept = float(dest["searcher_kept_usd"])
    if kept >= 0:
        dests.append(("Searchers kept", kept, p.searcher))
    else:
        sources.append(("Paid by searchers beyond their profit", -kept, p.searcher))
    s, d = sum(n[1] for n in sources), sum(n[1] for n in dests)
    if abs(s - d) > 1e-6 * max(s, 1.0):
        raise ValueError(f"destination flows do not balance: sources {s:,.2f} vs {d:,.2f}")
    return sources, dests


def pieces(sources: list[Node], dests: list[Node]) -> list[tuple[int, int, float]]:
    """Fill destinations in order from sources in order: (source index, destination index, USD)."""
    out: list[tuple[int, int, float]] = []
    rs, rd = [n[1] for n in sources], [n[1] for n in dests]
    i = j = 0
    eps = 1e-9 * max(sum(rs), 1.0)
    while i < len(rs) and j < len(rd):
        a = min(rs[i], rd[j])
        if a > eps:
            out.append((i, j, a))
        rs[i] -= a
        rd[j] -= a
        if rs[i] <= eps:
            i += 1
        if rd[j] <= eps:
            j += 1
    return out


def _band(ax: Any, y0a: float, y0b: float, y1a: float, y1b: float, color: str) -> None:
    """A band from [y0b, y0a] on the left to [y1b, y1a] on the right (cubic Bézier edges)."""
    x0, x1 = X_LEFT + NODE_W, X_RIGHT
    xm = (x0 + x1) / 2
    verts = [
        (x0, y0a),
        (xm, y0a),
        (xm, y1a),
        (x1, y1a),
        (x1, y1b),
        (xm, y1b),
        (xm, y0b),
        (x0, y0b),
        (x0, y0a),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.LINETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CLOSEPOLY,
    ]
    ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=color, alpha=0.38, lw=0))


def hero(r: Results, size: tuple[float, float] = CANVAS) -> Figure:
    p = pal()
    lp = r.summary["lp"]
    dest = lp["destination"]
    sources, dests = flows(dest, p)
    lvr = float(dest["lvr_on_searcher_swaps_usd"])
    fig = plt.figure(figsize=size)
    ax = fig.add_axes((0.03, 0.10, 0.50, 0.66))
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    gap = 0.014
    total = sum(n[1] for n in dests)
    scale = (1 - gap * (len(dests) - 1)) / total
    right, y = [], 1.0
    for label, v, c in dests:
        h = v * scale
        ax.add_patch(Rectangle((X_RIGHT, y - h), NODE_W, h, color=c, lw=0))
        ax.text(
            X_RIGHT + NODE_W + 0.02,
            y - h / 2,
            f"{label}  {usd(v)} · {pct(v / lvr)}",
            va="center",
            fontsize=9.5,
            color=p.ink,
            clip_on=False,
        )
        right.append([y, y - h])
        y -= h + gap
    height = total * scale
    left, y = [], 0.5 + height / 2
    for label, v, c in sources:
        h = v * scale
        ax.add_patch(
            Rectangle(
                (X_LEFT, y - h),
                NODE_W,
                h,
                color=c,
                lw=0,
                hatch="///" if label.startswith("Paid") else None,
                fill=True,
            )
        )
        ax.text(
            X_LEFT - 0.02,
            y - h / 2,
            f"{label}\n{usd(v)}",
            va="center",
            ha="right",
            fontsize=9.5,
            color=c,
            fontweight="bold",
            clip_on=False,
        )
        left.append([y, y - h])
        y -= h
    for i, j, a in pieces(sources, dests):
        h = a * scale
        _band(ax, left[i][0], left[i][0] - h, right[j][0], right[j][0] - h, dests[j][2])
        left[i][0] -= h
        right[j][0] -= h
    # Hatched band: how far the proposer/builder boundary moves under the self-built sensitivity.
    names = [n[0] for n in dests]
    if "Block builders" in names and "Proposers" in names:
        k = names.index("Proposers")
        top_prop = 1.0 - sum(n[1] * scale + gap for n in dests[:k])
        delta = float(dest["sensitivity_self_built"]["proposer_usd"]) - float(dest["proposer_usd"])
        h = abs(delta) * scale
        y0 = top_prop - h if delta < 0 else top_prop
        ax.add_patch(
            Rectangle(
                (X_RIGHT - 0.012, y0),
                NODE_W + 0.024,
                h,
                fill=False,
                hatch="xxx",
                edgecolor=p.muted,
                lw=0.6,
            )
        )
    share_bp = (float(dest["builder_margin_usd"]) + float(dest["proposer_usd"])) / lvr
    kept = float(dest["searcher_kept_usd"])
    stats = (
        (usd(float(lp["fees_minus_lvr_usd"])), "LP fees minus LVR\nover the window", p.lvr),
        (pct(share_bp), "of searcher LVR went to\nblock builders and proposers", p.builder),
        (usd(kept), "kept by searchers at block\ntime (an upper bound)", p.searcher),
    )
    for n, (big, small, c) in enumerate(stats):
        yy = 0.70 - n * 0.19
        fig.text(0.80, yy, big, fontsize=24, fontweight="bold", color=c, va="top")
        fig.text(0.80, yy - 0.075, small, fontsize=9.5, color=p.muted, va="top")
    frame(
        fig,
        f"Where {usd(lvr)} of arbitrage went",
        f"LVR on searcher swaps, Uniswap V3 USDC/WETH 0.05%, Jul–Sep 2026: "
        f"{pct(float(dest['fees_on_searcher_swaps_usd']) / lvr)} came back to LPs as fees, "
        f"{pct(share_bp)} went to block builders and proposers.",
        "Primary split shown; the hatched box is how far the proposer/builder boundary moves "
        "under the self-built-block sensitivity. Searchers' kept is measured at block time.",
    )
    return fig


def social_card(r: Results, out_dir: Path) -> list[Path]:
    """The hero as a 1280×640 PNG, for the repository's social preview and posts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / CARD_NAME
    with theme("light"):
        fig = hero(r, size=(12.8, 6.4))
        fig.savefig(path, dpi=100, metadata={"Software": None})
        plt.close(fig)
    return [path]
