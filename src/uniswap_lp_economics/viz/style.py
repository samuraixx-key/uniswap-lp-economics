"""Light house style, bundled Inter font, aligned text and deterministic SVG output."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from cycler import cycler  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from uniswap_lp_economics.config import ROOT  # noqa: E402

FONT_DIR = ROOT / "assets" / "fonts"
FONT_FILES = ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")
FONT = "Inter"
CANVAS = (11.5, 7.2)
MODES = ("light",)
SVG_SALT = "ulpe-figures"
SUBTITLE_CHARS = 112  # 10.5 pt subtitle on the 10 in canvas
SOURCE_CHARS = 150  # 8.3 pt source line


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
    """Wrap using the actual Inter glyph widths and the available figure width."""
    renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
    font = font_manager.FontProperties(family=FONT, size=fontsize, weight=weight)
    limit = fig.bbox.width * width
    paragraphs = []
    for paragraph in text.split("\n"):
        lines: list[str] = []
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            pixels = renderer.get_text_width_height_descent(candidate, font, False)[0]
            if line and (pixels > limit or len(candidate) > max_chars):
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
        # Avoid a tiny final line without changing the wording.
        if len(lines) > 1 and len(lines[-1]) < 22:
            words = lines[-2].split()
            while len(words) > 4 and len(lines[-1]) < 22:
                lines[-1] = words.pop() + " " + lines[-1]
            lines[-2] = " ".join(words)
        paragraphs.append("\n".join(lines))
    return "\n".join(paragraphs)


def frame(fig: Figure, title: str, subtitle: str, source: str) -> None:
    """Aligned header and footer, reserving space for wrapped text before the plot."""
    p = pal()
    renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
    left, width = 0.065, 0.88
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
    positions = [ax.get_position().frozen() for ax in fig.axes]
    old_bottom, old_top = min(b.y0 for b in positions), max(b.y1 for b in positions)
    top = min(old_top, sub.get_window_extent(renderer).y0 / fig.bbox.height - 0.065)
    bottom = max(old_bottom, foot.get_window_extent(renderer).y1 / fig.bbox.height + 0.10)
    for ax, box in zip(fig.axes, positions, strict=True):
        scale = (top - bottom) / (old_top - old_bottom)
        ax.set_position(
            (box.x0, bottom + (box.y0 - old_bottom) * scale, box.width, box.height * scale)
        )
        for loc in ("left", "center", "right"):
            panel_title = ax.get_title(loc=loc)
            if panel_title:
                ax.set_title(
                    _fit_text(fig, panel_title, 10.5, box.width, 80),
                    loc=loc,
                    fontsize=10.5,
                    linespacing=1.3,
                )


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
