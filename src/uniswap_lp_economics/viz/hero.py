"""The hero (README top): where the LVR on searcher swaps went, as a Sankey, with the uncertain
proposer/builder split hatched between the two flows; also the 1280×640 social card."""

import textwrap
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path as MplPath

from uniswap_lp_economics.viz.data import Results, window_label
from uniswap_lp_economics.viz.style import CANVAS, Palette, frame, pal, pct, theme, usd

Node = tuple[str, float, str]
CARD_NAME = "00_hero.png"
DEST_KEYS = (
    ("fees_on_searcher_swaps_usd", "LP fees", "fees"),
    ("protocol_fees_on_searcher_swaps_usd", "Protocol fees", "protocol"),
    ("multi_pool_gross_usd", "Multi-pool (not split)", "other"),
    ("gas_burned_usd", "Gas burned", "faint"),
    ("builder_margin_usd", "Block builders", "builder"),
    ("proposer_usd", "Proposers", "proposer"),
)
X_LEFT, X_RIGHT, NODE_W = 0.0, 0.80, 0.03
UNCERTAIN = "Builders or proposers"
HATCH = "////"
CARD_PX, CARD_DPI = (1280, 640), 125


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


def split_uncertain(dests: list[Node], moved: float) -> list[Node]:
    """Pull the slice the self-built-block sensitivity moves between builders and proposers out as
    its own node, UNCERTAIN, between the two. `moved` is the sensitivity's proposer USD minus the
    primary's: negative takes the slice out of the proposers, positive out of the builders."""
    names = [n[0] for n in dests]
    if moved == 0 or "Block builders" not in names or "Proposers" not in names:
        return list(dests)
    kb, kp = names.index("Block builders"), names.index("Proposers")
    if kp != kb + 1:
        return list(dests)
    (bl, bv, bc), (ql, qv, qc) = dests[kb], dests[kp]
    if moved < 0:
        m = min(-moved, qv)
        qv -= m
    else:
        m = min(moved, bv)
        bv -= m
    return [*dests[:kb], (bl, bv, bc), (UNCERTAIN, m, qc), (ql, qv, qc), *dests[kp + 1 :]]


def share(x: float) -> str:
    """A percentage, where a small positive share reads "<1%" rather than "0%"."""
    return "<1%" if 0 < x < 0.005 else pct(x)


def _band(
    ax: Any, y0a: float, y0b: float, y1a: float, y1b: float, color: str, hatch: str | None = None
) -> None:
    """A band from [y0b, y0a] on the left to [y1b, y1a] on the right (cubic Bézier edges); with
    `hatch`, hatched in that colour over the fill."""
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
    path = MplPath(verts, codes)
    ax.add_patch(PathPatch(path, facecolor=color, alpha=0.38, lw=0))
    if hatch is not None:
        ax.add_patch(PathPatch(path, fill=False, hatch=HATCH, edgecolor=hatch, lw=0, alpha=0.8))


def hero(r: Results, size: tuple[float, float] = CANVAS) -> Figure:
    p = pal()
    lp = r.summary["lp"]
    dest = lp["destination"]
    sources, primary = flows(dest, p)
    moved = float(dest["sensitivity_self_built"]["proposer_usd"]) - float(dest["proposer_usd"])
    dests = split_uncertain(primary, moved)
    lvr = float(dest["lvr_on_searcher_swaps_usd"])
    fig = plt.figure(figsize=size)
    ax = fig.add_axes((0.17, 0.10, 0.36, 0.66))
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    gap = 0.014
    joined = {"Block builders", UNCERTAIN, "Proposers"}  # one stack, no gaps inside it
    gaps = [
        0.0 if a[0] in joined and b[0] in joined else gap
        for a, b in zip(dests[:-1], dests[1:], strict=True)
    ]
    total = sum(n[1] for n in dests)
    scale = (1 - sum(gaps)) / total
    right, y = [], 1.0
    for j, (label, v, c) in enumerate(dests):
        h = v * scale
        uncertain = label == UNCERTAIN
        ax.add_patch(
            Rectangle(
                (X_RIGHT, y - h),
                NODE_W,
                h,
                facecolor=c,
                edgecolor=p.builder if uncertain else c,
                hatch=HATCH if uncertain else None,
                lw=0,
                gid=f"node:{label}",
            )
        )
        right.append([y, y - h])
        y -= h + (gaps[j] if j < len(gaps) else 0.0)
    # Labels give the primary split: the uncertain slice counts with the flow it came out of.
    spans = {n[0]: (top, bottom) for n, (top, bottom) in zip(dests, right, strict=True)}
    if UNCERTAIN in spans:
        owner = "Proposers" if moved < 0 else "Block builders"
        top, bottom = spans[owner]
        u_top, u_bottom = spans[UNCERTAIN]
        spans[owner] = (max(top, u_top), min(bottom, u_bottom))
    for label, v, _ in primary:
        top, bottom = spans[label]
        ax.text(
            X_RIGHT + NODE_W + 0.02,
            (top + bottom) / 2,
            f"{label}  {usd(v)} · {share(v / lvr)}",
            va="center",
            fontsize=9.5,
            color=p.ink,
            clip_on=False,
        )
    height = 1.0 - right[-1][1]
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
            f"{textwrap.fill(label, 16)}\n{usd(v)}",
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
        _band(
            ax,
            left[i][0],
            left[i][0] - h,
            right[j][0],
            right[j][0] - h,
            dests[j][2],
            hatch=p.builder if dests[j][0] == UNCERTAIN else None,
        )
        left[i][0] -= h
        right[j][0] -= h
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
        f"LVR on searcher swaps, Uniswap V3 USDC/WETH 0.05%, {window_label(r.daily)}:\n"
        f"{pct(float(dest['fees_on_searcher_swaps_usd']) / lvr)} came back to LPs as fees, "
        f"{pct(share_bp)} went to block builders and proposers.",
        _footnote(dests, moved, kept),
    )
    return fig


def _footnote(dests: list[Node], moved: float, kept: float) -> str:
    parts = ["Primary split shown."]
    m = next((n[1] for n in dests if n[0] == UNCERTAIN), 0.0)
    if m > 0:
        way = "proposers to builders" if moved < 0 else "builders to proposers"
        parts.append(
            f"Hatched: the {usd(m)} that moves from {way} under the self-built-block sensitivity."
        )
    if kept < 0:
        parts.append(
            f"Searchers paid out {usd(-kept)} more than their arbitrage made, drawn as a second "
            "source; kept is measured at block time."
        )
    else:
        parts.append("Searchers' kept is measured at block time.")
    return " ".join(parts)


def card_figure(r: Results) -> Figure:
    """The hero laid out for the social card: a smaller canvas rendered at a higher dpi, so the
    text is larger relative to the 1280×640 image."""
    return hero(r, size=(CARD_PX[0] / CARD_DPI, CARD_PX[1] / CARD_DPI))


def social_card(r: Results, out_dir: Path) -> list[Path]:
    """The hero as a 1280×640 PNG, for the repository's social preview and posts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / CARD_NAME
    with theme("light"):
        fig = card_figure(r)
        fig.savefig(path, dpi=CARD_DPI, metadata={"Software": None})
        plt.close(fig)
    return [path]
