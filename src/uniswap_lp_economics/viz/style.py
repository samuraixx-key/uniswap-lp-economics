"""Light house style, bundled Inter font, aligned text and deterministic SVG output."""

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from weakref import WeakKeyDictionary

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from cycler import cycler  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.text import Text  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from matplotlib.transforms import Bbox  # noqa: E402

from uniswap_lp_economics.config import ROOT  # noqa: E402

FONT_DIR = ROOT / "assets" / "fonts"
FONT_FILES = ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")
FONT = "Inter"
CANVAS = (11.5, 7.2)
MODES = ("light",)
SVG_SALT = "ulpe-figures"
SUBTITLE_CHARS = 150  # 10.5 pt subtitle across the 11.5 in canvas
SOURCE_CHARS = 190  # 8.5 pt source line
# vertical gaps, as figure fractions: subtitle to the panel headers (or the plot), headers to the
# plot's top, the plot's lowest label to the source line
GAP_SUBTITLE = 0.045
GAP_HEADER = 0.025
GAP_SOURCE = 0.035
# panel headers: rule to the heading baseline, heading baseline to the description baseline
HEADER_BASELINE = 0.031
DESCRIPTION_BASELINE = 0.036
NBSP = "\u00a0"
UNIT_BREAK = re.compile(r"(?<=\d) (?=(?:bp|s|ms|min|h|days?|blocks?|swaps?|positions?)\b)")


@dataclass(frozen=True)
class Palette:
    background: str
    ink: str
    muted: str
    faint: str
    grid: str
    lvr: str
    fees: str
    jit: str
    other: str
    protocol: str
    builder: str
    proposer: str
    searcher: str
    binance: str


PALETTES = {
    "light": Palette(
        background="#FFFFFF",
        ink="#1F2933",
        muted="#5F6B76",
        faint="#8D969F",
        grid="#E7EAEE",
        lvr="#C2553A",
        fees="#2A7F9E",
        jit="#E0A030",
        other="#8A96A3",
        protocol="#6C5B9E",
        builder="#3F7D5A",
        proposer="#86B486",
        searcher="#B5838D",
        binance="#1F2933",
    ),
}
_current: Palette | None = None


def register_fonts() -> None:
    """Register the bundled Inter files; a missing file raises instead of falling back."""
    for name in FONT_FILES:
        path = FONT_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"{path} missing: the figures need the bundled Inter font")
        font_manager.fontManager.addfont(str(path))


def _rc(p: Palette) -> dict[str, Any]:
    return {
        "font.family": [FONT],
        "font.size": 10.5,
        "mathtext.fontset": "dejavusans",
        "text.parse_math": False,  # "$" is money here; math only where asked for
        "text.color": p.ink,
        "axes.facecolor": p.background,
        "figure.facecolor": p.background,
        "savefig.facecolor": p.background,
        "axes.labelcolor": p.muted,
        "axes.edgecolor": p.faint,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.axisbelow": True,  # gridlines behind bars as well as lines
        "axes.labelsize": 10,
        "axes.prop_cycle": cycler(color=[p.fees, p.lvr, p.jit, p.other]),
        "grid.color": p.grid,
        "grid.linewidth": 0.8,
        "xtick.color": p.muted,
        "ytick.color": p.muted,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "svg.fonttype": "path",
        "svg.hashsalt": SVG_SALT,
    }


@contextmanager
def theme(mode: str) -> Iterator[Palette]:
    """Light house style for everything drawn inside the block."""
    global _current
    if mode not in PALETTES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    register_fonts()
    p, previous = PALETTES[mode], _current
    with plt.rc_context(_rc(p)):  # type: ignore[arg-type]  # rcParams keys typed as literals
        _current = p
        try:
            yield p
        finally:
            _current = previous


def pal() -> Palette:
    if _current is None:
        raise RuntimeError("pal() called outside a theme() block")
    return _current


def new_figure(
    nrows: int = 1,
    ncols: int = 1,
    *,
    size: tuple[float, float] = CANVAS,
    left: float = 0.085,
    right: float = 0.97,
    top: float = 0.78,
    bottom: float = 0.17,
    wspace: float | None = None,
    **subplot_kw: Any,
) -> tuple[Figure, Any]:
    """A figure on the standard canvas, with room above for `frame`'s title block."""
    fig, axes = plt.subplots(nrows, ncols, figsize=size, **subplot_kw)
    fig.subplots_adjust(left=left, right=right, top=top, bottom=bottom, wspace=wspace)
    return fig, axes


def _fit_text(
    fig: Figure, text: str, fontsize: float, width: float, max_chars: int, weight: str = "normal"
) -> str:
    """Wrap using the actual Inter glyph widths and the available figure width. A number never
    wraps away from its unit ("2.86 bp")."""
    renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
    font = font_manager.FontProperties(family=FONT, size=fontsize, weight=weight)
    limit = fig.bbox.width * width

    widths: dict[str, float] = {}

    def measure(line: str) -> float:
        if line not in widths:
            widths[line] = renderer.get_text_width_height_descent(line, font, False)[0]
        return widths[line]

    def wrap(words: list[str], pixels: float) -> list[str]:
        lines: list[str] = []
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            wide = measure(candidate) > pixels
            if line and (wide or len(candidate) > max_chars):
                lines.append(line)
                line = word
            else:
                line = candidate
        return [*lines, line]

    paragraphs = []
    for paragraph in UNIT_BREAK.sub(NBSP, text).split("\n"):
        words = re.split(r" +", paragraph.strip())
        lines = wrap(words, limit)
        if len(lines) > 1:  # balance: the narrowest width that keeps the same number of lines
            lo, hi = limit / 2, limit
            for _ in range(8):  # within 0.4% of the narrowest width
                mid = (lo + hi) / 2
                lo, hi = (lo, mid) if len(wrap(words, mid)) == len(lines) else (mid, hi)
            lines = wrap(words, hi)
        paragraphs.append("\n".join(lines))
    return "\n".join(paragraphs).replace(NBSP, " ")


@dataclass(frozen=True)
class PanelHeader:
    number: int | None
    title: str
    description: str = ""
    color: str | None = None


_HEADERS: "WeakKeyDictionary[Axes, PanelHeader]" = WeakKeyDictionary()


def panel_header(
    ax: Axes, number: int | None, title: str, description: str = "", color: str | None = None
) -> None:
    """Give a panel a header: a rule across its top, the panel number, a heading and a short
    description. `frame` draws it, so call this first."""
    _HEADERS[ax] = PanelHeader(number, title, description, color)


def panel_headers(fig: Figure) -> list[PanelHeader]:
    return [_HEADERS[ax] for ax in fig.axes if ax in _HEADERS]


def _px(fig: Figure, artist: Any) -> Bbox:
    return artist.get_window_extent(fig.canvas.get_renderer())  # type: ignore[attr-defined, no-any-return]


def _mid_y(fig: Figure, artist: Any) -> float:
    box = _px(fig, artist)
    return float((box.y0 + box.y1) / 2)


def _left_edge(fig: Figure, ax: Axes) -> float:
    """Left edge of the panel's visible y tick labels (the axes edge without any), as a figure
    fraction: headers line up with the numbers, not with the axis line."""
    box = _px(fig, ax)
    xs = [
        _px(fig, t).x0
        for t in ax.get_yticklabels()
        if t.get_visible() and t.get_text() and box.y0 - 1 <= _mid_y(fig, t) <= box.y1 + 1
    ]
    return float(min([box.x0, *xs]) / fig.bbox.width)


def _baseline_text(fig: Figure, x: float, y: float, s: str, **kw: Any) -> Text:
    """Text whose first line sits on the baseline `y` (figure fraction), whatever its letters:
    `va="top"` would move it with the tallest glyph. Matplotlib anchors the last line, so the text
    moves down by the distance between its first and last baselines."""
    t = fig.text(x, y, s, va="baseline", **kw)
    _, lines, _ = t._get_layout(fig.canvas.get_renderer())  # type: ignore[attr-defined]
    drop = lines[0][2][1] - lines[-1][2][1]  # (text, (w, h, d), (x, y)) per line
    t.set_y(y - drop / fig.bbox.height)
    return t


def _draw_headers(fig: Figure, top: float) -> list[tuple[Axes, Line2D, list[Text], float]]:
    p = pal()
    drawn = []
    for ax in fig.axes:
        h = _HEADERS.get(ax)
        if h is None:
            continue
        x0, x1 = _left_edge(fig, ax), ax.get_position().x1
        rule = Line2D([x0, x1], [top, top], transform=fig.transFigure, color=p.ink, lw=1.0)
        rule.set_gid("panel-rule")
        fig.add_artist(rule)
        y, dx, texts = top - HEADER_BASELINE, 0.0, []
        if h.number is not None:
            num = _baseline_text(
                fig, x0, y, str(h.number), fontsize=11.5, fontweight="semibold", color=p.lvr
            )
            num.set_gid("panel-number")
            texts.append(num)
            dx = _px(fig, num).width / fig.bbox.width + 0.008
        width = x1 - x0 - dx
        head = _baseline_text(
            fig,
            x0 + dx,
            y,
            _fit_text(fig, h.title, 11.5, width, 200, "semibold"),
            fontsize=11.5,
            fontweight="semibold",
            color=h.color or p.ink,
            linespacing=1.25,
        )
        head.set_gid("panel-heading")
        texts.append(head)
        if h.description:
            desc = _baseline_text(
                fig,
                x0 + dx,
                head.get_position()[1] - DESCRIPTION_BASELINE,  # under the heading's last line
                _fit_text(fig, h.description, 9.5, width, 200),
                fontsize=9.5,
                color=p.muted,
                linespacing=1.35,
            )
            desc.set_gid("panel-description")
            texts.append(desc)
        drawn.append((ax, rule, texts, x0))
    return drawn


def _place_axes(fig: Figure, top: float, bottom: float) -> None:
    """Scale the panels so that everything they draw (tick labels, axis labels, annotations) fits
    between `top` and `bottom`, figure fractions."""
    renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
    height = fig.bbox.height
    for _ in range(2):  # tick labels can change with the new size; settle once more
        positions = [ax.get_position().frozen() for ax in fig.axes]
        old_bottom, old_top = min(b.y0 for b in positions), max(b.y1 for b in positions)
        boxes = [ax.get_tightbbox(renderer) for ax in fig.axes]
        tight = Bbox.union([b for b in boxes if b is not None])
        above = max(tight.y1 / height - old_top, 0.0)
        below = max(old_bottom - tight.y0 / height, 0.0)
        new_top, new_bottom = top - above, bottom + below
        new_bottom = min(new_bottom, new_top - 0.15)
        scale = (new_top - new_bottom) / (old_top - old_bottom)
        for ax, box in zip(fig.axes, positions, strict=True):
            ax.set_position(
                (box.x0, new_bottom + (box.y0 - old_bottom) * scale, box.width, box.height * scale)
            )


def frame(fig: Figure, title: str, subtitle: str, source: str) -> None:
    """Aligned title, subtitle and source line; panel headers (see `panel_header`) between the
    subtitle and the plot; the panels scaled to fill the space left."""
    p = pal()
    renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
    left, width = 0.065, 0.90
    heading = fig.text(
        left,
        0.96,
        _fit_text(fig, title, 16, width, 110, "bold"),
        fontsize=16,
        fontweight="bold",
        va="top",
        color=p.ink,
        gid="title",
        linespacing=1.25,
    )
    heading_bottom = heading.get_window_extent(renderer).y0 / fig.bbox.height
    sub = fig.text(
        left,
        heading_bottom - 0.018,
        _fit_text(fig, subtitle, 10.5, width, SUBTITLE_CHARS),
        fontsize=10.5,
        va="top",
        color=p.muted,
        gid="subtitle",
        linespacing=1.4,
    )
    foot = fig.text(
        left,
        0.028,
        _fit_text(fig, source, 8.5, width, SOURCE_CHARS),
        fontsize=8.5,
        va="bottom",
        color=p.muted,
        gid="source",
        linespacing=1.4,
    )
    if not fig.axes:
        return
    for ax in fig.axes:
        for loc in ("left", "center", "right"):
            panel_title = ax.get_title(loc=loc)
            if panel_title:
                ax.set_title(
                    _fit_text(fig, panel_title, 10.5, ax.get_position().width, 80),
                    loc=loc,
                    fontsize=10.5,
                    linespacing=1.3,
                )
    height = fig.bbox.height
    top = sub.get_window_extent(renderer).y0 / height - GAP_SUBTITLE
    bottom = foot.get_window_extent(renderer).y1 / height + GAP_SOURCE
    headers = _draw_headers(fig, top)
    if headers:
        top = min(_px(fig, t).y0 for _, _, texts, _ in headers for t in texts) / height
        top -= GAP_HEADER
    _place_axes(fig, top, bottom)
    for ax, rule, texts, old_x0 in headers:  # the tick labels may have moved: line up again
        x0 = _left_edge(fig, ax)
        shift = x0 - old_x0
        rule.set_xdata([x0, ax.get_position().x1])
        for t in texts:
            t.set_x(t.get_position()[0] + shift)


def usd(x: float) -> str:
    a = abs(x)
    if a >= 1e6:
        s = f"${a / 1e6:.1f}M"
    elif a >= 1e4:
        s = f"${a / 1e3:.0f}k"
    elif a >= 1e3:
        s = f"${a / 1e3:.1f}k"
    else:
        s = f"${a:.0f}"
    return ("−" if x < 0 and s != "$0" else "") + s


def pct(x: float) -> str:
    return f"{x:.0%}"


USD_FMT = FuncFormatter(lambda v, _: usd(v))


def per_10k_month(bp_per_day: float) -> float:
    """bp of position value per day -> USD per $10,000 of value per 30 days (spec section 6)."""
    return bp_per_day * 30.0


def fade_band(
    ax: Axes,
    x: Sequence[float],
    lo: Sequence[float],
    hi: Sequence[float],
    color: str,
    layers: int = 4,
    alpha: float = 0.30,
) -> None:
    """An interval band that fades towards its edges (nested fills, darkest in the middle)."""
    xs, lows, highs = np.asarray(x, float), np.asarray(lo, float), np.asarray(hi, float)
    mid = (lows + highs) / 2
    for k in range(layers):
        f = (k + 1) / layers
        ax.fill_between(
            xs,
            mid - (mid - lows) * f,
            mid + (highs - mid) * f,
            color=color,
            alpha=alpha / layers,
            lw=0,
        )


def no_data(ax: Axes, text: str = "no data") -> None:
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes, color=pal().muted)


def save_svg(fig: Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="svg", metadata={"Date": None})
    plt.close(fig)


def svg_bytes(fig: Figure) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="svg", metadata={"Date": None})
    plt.close(fig)
    return buf.getvalue()
