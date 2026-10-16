"""House style for every figure (chart redesign spec sections 5 and 7): palettes for light and dark
mode, the bundled Inter font, the title block, formatters and deterministic SVG output."""

import textwrap
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
CANVAS = (10.0, 6.2)
MODES = ("light", "dark")
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
    "dark": Palette(
        background="#0D1117",
        ink="#E6EDF3",
        muted="#9AA5B1",
        faint="#6E7781",
        grid="#21262D",
        lvr="#E07A5F",
        fees="#4FB3D9",
        jit="#F2B84B",
        other="#7D8B99",
        protocol="#A291D9",
        builder="#6FBF8B",
        proposer="#A8D5A8",
        searcher="#E8A0AE",
        binance="#E6EDF3",
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
    """Light or dark house style for everything drawn inside the block."""
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
    top: float = 0.80,
    bottom: float = 0.15,
    wspace: float | None = None,
    **subplot_kw: Any,
) -> tuple[Figure, Any]:
    """A figure on the standard canvas, with room above for `frame`'s title block."""
    fig, axes = plt.subplots(nrows, ncols, figsize=size, **subplot_kw)
    fig.subplots_adjust(left=left, right=right, top=top, bottom=bottom, wspace=wspace)
    return fig, axes


def _wrap(text: str, width: int) -> str:
    """Wrap each paragraph line to `width` characters; explicit line breaks are kept."""
    return "\n".join(textwrap.fill(line, width) for line in text.split("\n"))


def frame(fig: Figure, title: str, subtitle: str, source: str) -> None:
    """Headline stating the finding, a muted subtitle with the key numbers, a source line. Long
    subtitle and source lines wrap to the canvas width."""
    p = pal()
    fig.text(
        0.012, 0.975, title, fontsize=15.5, fontweight="bold", va="top", color=p.ink, gid="title"
    )
    fig.text(
        0.012,
        0.92,
        _wrap(subtitle, SUBTITLE_CHARS),
        fontsize=10.5,
        va="top",
        color=p.muted,
        gid="subtitle",
    )
    fig.text(
        0.012,
        0.012,
        _wrap(source, SOURCE_CHARS),
        fontsize=8.3,
        va="bottom",
        color=p.faint,
        gid="source",
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
