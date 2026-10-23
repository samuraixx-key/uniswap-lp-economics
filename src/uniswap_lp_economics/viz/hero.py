"""The hero (README top): where the LVR on searcher swaps went, as a two-stage Sankey. The LVR first
splits into the swap fees searchers paid and their gross profit; the fees end with LPs and the
protocol, the gross profit (topped up by any money searchers paid beyond it) with block builders,
proposers, gas and multi-pool arbitrage. The uncertain proposer/builder split is hatched between
the two flows. Also the 1280×640 social card."""

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path as MplPath
from matplotlib.text import Text

from uniswap_lp_economics.viz.data import Results, window_label
from uniswap_lp_economics.viz.style import CANVAS, Palette, frame, pal, pct, theme, usd

Node = tuple[str, float, str]
Link = tuple[int, int, float]  # (from index, to index, USD)
CARD_NAME = "00_hero.png"
DEST_KEYS = (
    ("fees_on_searcher_swaps_usd", "LP fees", "fees"),
    ("protocol_fees_on_searcher_swaps_usd", "Protocol fees", "protocol"),
    ("multi_pool_gross_usd", "Multi-pool (not split)", "other"),
    ("gas_burned_usd", "Gas burned", "faint"),
    ("builder_margin_usd", "Block builders", "builder"),
    ("proposer_usd", "Proposers", "proposer"),
)
FEE_SIDE = ("LP fees", "Protocol fees")
FEES_NODE = "Paid as swap fees"
GROSS_NODE = "Searchers' gross profit"
SOURCE_NAMES = {"Paid by searchers beyond their profit": "Searchers' own money"}
SOURCE_BREAKS = {
    "LVR on searcher swaps": "LVR on\nsearcher swaps",
    "Searchers' own money": "Searchers'\nown money",
}
COLUMN_HEADERS = ("ARBITRAGE", "FIRST SPLIT", "WHERE IT ENDED")
COLS = (0.0, 0.47, 0.94)  # x of the three node columns, axes fraction
NODE_W = 0.022
GAP = 0.03  # between nodes, axes fraction
LABEL_PT = 34.0  # height of one end label (share over name), points
UNCERTAIN = "Builders or proposers"
HATCH = "////"
BAND_ALPHA = 0.5
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


def pieces(sources: list[Node], dests: list[Node]) -> list[Link]:
    """Fill destinations in order from sources in order: (source index, destination index, USD)."""
    out: list[Link] = []
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


@dataclass(frozen=True)
class Stages:
    sources: list[Node]  # column 0: the LVR first
    middle: list[Node]  # column 1: FEES_NODE, GROSS_NODE (value = what each passes on)
    dests: list[Node]  # column 2: the fee side, then the searcher side
    stage1: list[Link]  # source -> middle
    stage2: list[Link]  # middle -> destination


def stages(dest: dict[str, Any], p: Palette) -> Stages:
    """The two-stage split. The LVR pays the swap fees first; what is left is the searchers' gross
    profit, which every other source (money searchers paid beyond their profit, a negative flow)
    tops up before it ends with the searcher-side destinations."""
    sources, dests = flows(dest, p)
    fee_side = [n for n in dests if n[0] in FEE_SIDE]
    rest = [n for n in dests if n[0] not in FEE_SIDE]
    fees = sum(n[1] for n in fee_side)
    if fees > sources[0][1]:
        raise ValueError(
            "swap fees exceed the LVR on searcher swaps: there is no gross profit to draw"
        )
    middle = [(FEES_NODE, fees, p.fees), (GROSS_NODE, sum(n[1] for n in rest), p.searcher)]
    stage2 = [(0, j, a) for _, j, a in pieces([middle[0]], fee_side)]
    stage2 += [(1, len(fee_side) + j, a) for _, j, a in pieces([middle[1]], rest)]
    return Stages(sources, middle, fee_side + rest, pieces(sources, middle), stage2)


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
    ax: Axes,
    x: tuple[float, float],
    left: tuple[float, float],
    right: tuple[float, float],
    colors: tuple[str, str],
    hatch: str | None = None,
) -> None:
    """A band from [left] (top, bottom) at x[0] to [right] at x[1] with cubic Bézier edges, its
    colour graded from colors[0] to colors[1]; with `hatch`, hatched in that colour over it."""
    x0, x1 = x
    xm = (x0 + x1) / 2
    verts = [
        (x0, left[0]),
        (xm, left[0]),
        (xm, right[0]),
        (x1, right[0]),
        (x1, right[1]),
        (xm, right[1]),
        (xm, left[1]),
        (x0, left[1]),
        (x0, left[0]),
    ]
    codes = [MplPath.MOVETO, *[MplPath.CURVE4] * 3, MplPath.LINETO]
    codes += [*[MplPath.CURVE4] * 3, MplPath.CLOSEPOLY]
    path = MplPath(verts, codes)
    outline = PathPatch(path, facecolor="none", lw=0)
    ax.add_patch(outline)
    a, b = np.array(to_rgb(colors[0])), np.array(to_rgb(colors[1]))
    grade = a + (b - a) * np.linspace(0, 1, 64)[None, :, None]
    lo, hi = min(left[1], right[1]), max(left[0], right[0])
    image = ax.imshow(
        grade,
        extent=(x0, x1, lo, hi),
        aspect="auto",
        alpha=BAND_ALPHA,
        origin="lower",
        interpolation="bilinear",
        zorder=1,
    )
    image.set_clip_path(outline)
    if hatch is not None:
        ax.add_patch(
            PathPatch(path, fill=False, hatch=HATCH, edgecolor=hatch, lw=0, alpha=0.7, zorder=2)
        )


def spread(want: list[float], gap: float, floor: float) -> list[float]:
    """Label centres, top to bottom, as close to `want` as possible and at least `gap` apart; the
    lowest no lower than `floor`."""
    ys = list(want)
    for i in range(1, len(ys)):
        ys[i] = min(ys[i], ys[i - 1] - gap)
    if ys and ys[-1] < floor:
        ys[-1] = floor
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = max(ys[i], ys[i + 1] + gap)
    return ys


@dataclass
class EndLabel:
    want: float  # the node's centre, axes fraction
    big: Text
    small: Text
    connector: Line2D


def _place_end_labels(fig: Figure, ax: Axes, labels: list[EndLabel]) -> None:
    """Stack the end labels beside their nodes, LABEL_PT apart whatever the axes' final size, with
    a bent connector to any label moved off its node."""
    gap = LABEL_PT / 72 / (ax.get_position().height * fig.get_figheight())
    ys = spread([lab.want for lab in labels], gap, floor=-0.02)
    x_node = COLS[2] + NODE_W
    x_text = labels[0].big.get_position()[0] if labels else 0.0
    for lab, y in zip(labels, ys, strict=True):
        lab.big.set_y(y + 0.002)
        lab.small.set_y(y - 0.006)
        moved = abs(lab.want - y) > 0.004
        lab.connector.set_data([x_node + 0.006, x_node + 0.035, x_text - 0.015], [lab.want, y, y])
        lab.connector.set_visible(moved)


def hero(r: Results, size: tuple[float, float] = CANVAS) -> Figure:
    p = pal()
    lp = r.summary["lp"]
    dest = lp["destination"]
    st = stages(dest, p)
    sens = dest.get("sensitivity_self_built")  # only under the hedge
    moved = 0.0 if sens is None else float(sens["proposer_usd"]) - float(dest["proposer_usd"])
    lvr = st.sources[0][1]
    fees = st.middle[0][1]
    gross = next(a for i, m, a in st.stage1 if i == 0 and m == 1) if lvr > fees else 0.0
    drawn = split_uncertain(st.dests, moved)
    fig = plt.figure(figsize=size)
    ax = fig.add_axes((0.17, 0.12, 0.40, 0.62))
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # column 2, top to bottom: a wider gap between the fee side and the searcher side
    joined = {"Block builders", UNCERTAIN, "Proposers"}  # one stack, no gaps inside it
    gaps = []
    for upper, lower in zip(drawn[:-1], drawn[1:], strict=True):
        if upper[0] in joined and lower[0] in joined:
            gaps.append(0.0)
        elif (upper[0] in FEE_SIDE) != (lower[0] in FEE_SIDE):
            gaps.append(GAP * 1.6)
        else:
            gaps.append(GAP * 0.7)
    scale = (1 - sum(gaps)) / sum(n[1] for n in drawn)
    spans2: list[tuple[float, float]] = []
    y = 1.0
    for j, (label, v, c) in enumerate(drawn):
        h = v * scale
        uncertain = label == UNCERTAIN
        ax.add_patch(
            Rectangle(
                (COLS[2], y - h),
                NODE_W,
                h,
                facecolor=c,
                edgecolor=p.builder if uncertain else c,
                hatch=HATCH if uncertain else None,
                lw=0,
                zorder=3,
                gid=f"node:{label}",
            )
        )
        spans2.append((y, y - h))
        y -= h + (gaps[j] if j < len(gaps) else 0.0)
    children = [
        [j for j, n in enumerate(drawn) if n[0] in FEE_SIDE],
        [j for j, n in enumerate(drawn) if n[0] not in FEE_SIDE],
    ]

    # column 1: each middle node level with the top of its first end node
    spans1 = []
    for k, (_, v, c) in enumerate(st.middle):
        top = spans2[children[k][0]][0] if children[k] else 1.0
        spans1.append((top, top - v * scale))
        ax.add_patch(Rectangle((COLS[1], top - v * scale), NODE_W, v * scale, color=c, lw=0))

    # column 0: the sources, centred on the end column
    heights = [n[1] * scale for n in st.sources]
    extent = sum(heights) + GAP * (len(heights) - 1)
    y = (1.0 + spans2[-1][1]) / 2 + extent / 2
    spans0 = []
    for (label, _, c), h in zip(st.sources, heights, strict=True):
        spans0.append((y, y - h))
        ax.add_patch(
            Rectangle(
                (COLS[0], y - h),
                NODE_W,
                h,
                color=c,
                lw=0,
                hatch="///" if label in SOURCE_NAMES else None,
            )
        )
        y -= h + GAP

    # bands: each node hands out its flow from the top down
    out0 = [s[0] for s in spans0]
    in1 = [s[0] for s in spans1]
    for i, m, a in st.stage1:
        h = a * scale
        _band(
            ax,
            (COLS[0] + NODE_W, COLS[1]),
            (out0[i], out0[i] - h),
            (in1[m], in1[m] - h),
            (st.sources[i][2], st.middle[m][2]),
        )
        out0[i] -= h
        in1[m] -= h
    out1 = [s[0] for s in spans1]
    for k, kids in enumerate(children):
        for j in kids:
            h = drawn[j][1] * scale
            _band(
                ax,
                (COLS[1] + NODE_W, COLS[2]),
                (out1[k], out1[k] - h),
                spans2[j],
                (st.middle[k][2], drawn[j][2]),
                hatch=p.builder if drawn[j][0] == UNCERTAIN else None,
            )
            out1[k] -= h

    for x, text, ha in zip(
        (COLS[0], COLS[1] + NODE_W / 2, COLS[2]),
        COLUMN_HEADERS,
        ("left", "center", "left"),
        strict=True,
    ):
        ax.text(
            x,
            1.05,
            text,
            ha=ha,
            va="bottom",
            fontsize=8.5,
            fontweight="semibold",
            color=p.muted,
            clip_on=False,
        )
    for (label, v, c), (top, bottom) in zip(st.sources, spans0, strict=True):
        name = SOURCE_NAMES.get(label, label)
        name = SOURCE_BREAKS.get(name) or textwrap.fill(name, 14)
        ax.text(
            COLS[0] - 0.02,
            (top + bottom) / 2,
            f"{name}\n{usd(v)}",
            ha="right",
            va="center",
            fontsize=10,
            fontweight="semibold",
            color=c,
            linespacing=1.3,
            clip_on=False,
        )
    for (label, _, _), (top, bottom), passed in zip(st.middle, spans1, (fees, gross), strict=True):
        yc = (top + bottom) / 2
        ax.text(
            COLS[1] - 0.015,
            yc + 0.006,
            label,
            ha="right",
            va="bottom",
            fontsize=9.5,
            fontweight="semibold",
            color=p.ink,
            zorder=6,
        )
        ax.text(
            COLS[1] - 0.015,
            yc - 0.006,
            f"{usd(passed)} · {pct(passed / lvr)}",
            ha="right",
            va="top",
            fontsize=9,
            color=p.ink,
            zorder=6,
        )

    # end labels, share first; the builders' and proposers' values span the sensitivity
    spans = {n[0]: s for n, s in zip(drawn, spans2, strict=True)}
    if UNCERTAIN in spans:  # the uncertain slice counts with the flow it came out of
        owner = "Proposers" if moved < 0 else "Block builders"
        spans[owner] = (
            max(spans[owner][0], spans[UNCERTAIN][0]),
            min(spans[owner][1], spans[UNCERTAIN][1]),
        )
    alt = {"Block builders": "builder_margin_usd", "Proposers": "proposer_usd"}
    labels = []
    x_text = COLS[2] + NODE_W + 0.08
    for label, v, c in st.dests:
        value = usd(v)
        if moved != 0 and label in alt:
            lo, hi = sorted((v, float(sens[alt[label]])))
            value = f"{usd(lo)}–{usd(hi)}"
        top, bottom = spans[label]
        connector = Line2D([], [], color=p.faint, lw=0.8, clip_on=False)
        ax.add_line(connector)
        labels.append(
            EndLabel(
                (top + bottom) / 2,
                ax.text(
                    x_text,
                    0,
                    share(v / lvr),
                    fontsize=17,
                    fontweight="bold",
                    color=p.muted if c == p.faint else c,
                    va="bottom",
                    clip_on=False,
                ),
                ax.text(
                    x_text,
                    0,
                    f"{label} · {value}",
                    fontsize=9.3,
                    color=p.ink,
                    va="top",
                    clip_on=False,
                ),
                connector,
            )
        )
    _place_end_labels(fig, ax, labels)

    bp = float(dest["builder_margin_usd"]) + float(dest["proposer_usd"])
    kept = float(dest["searcher_kept_usd"])
    stats = (
        (pct(bp / lvr), "of the arbitrage went to block\nbuilders and proposers", p.builder),
        (usd(kept), "kept by searchers at block\ntime (an upper bound)", p.searcher),
    )
    sx = 0.80
    divider = Line2D([sx - 0.02] * 2, [0.30, 0.74], color=p.grid, lw=1, transform=fig.transFigure)
    fig.add_artist(divider)
    for n, (big, small, c) in enumerate(stats):
        yy = 0.70 - n * 0.24
        fig.text(sx, yy, big, fontsize=24, fontweight="bold", color=c, va="top")
        fig.text(sx, yy - 0.07, small, fontsize=9.3, color=p.muted, va="top", linespacing=1.35)
    took = "more than all of it" if bp > gross else f"{pct(bp / gross)} of it"
    lp_fees = next(v for label, v, _ in st.dests if label == "LP fees")
    frame(
        fig,
        f"Where {usd(lvr)} of arbitrage went",
        f"LVR on searcher swaps, Uniswap V3 USDC/WETH 0.05%, {window_label(r.daily)}. "
        f"{pct(lp_fees / lvr)} went to LPs as fees and {pct((fees - lp_fees) / lvr)} to the "
        f"protocol; of the searchers' {usd(gross)} gross profit, builders and proposers took "
        f"{took}.",
        _footnote(drawn, moved, kept),
    )
    _place_end_labels(fig, ax, labels)  # frame() resized the axes: restack at the final size
    return fig


def _footnote(dests: list[Node], moved: float, kept: float) -> str:
    parts = []
    m = next((n[1] for n in dests if n[0] == UNCERTAIN), 0.0)
    if m > 0:
        way = "proposers to builders" if moved < 0 else "builders to proposers"
        parts.append(
            f"Hatched: the {usd(m)} that moves from {way} under the self-built-block sensitivity; "
            "shares use the primary split."
        )
    if kept < 0:
        parts.append(
            f"Searchers' own money: the {usd(-kept)} they paid out beyond their arbitrage profit, "
            "drawn as a second source; measured at block time."
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
