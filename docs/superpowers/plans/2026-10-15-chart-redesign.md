# Chart and Presentation Redesign Implementation Plan

> **Status (2026-10-21): done, kept as the execution record.** What shipped differs in one way: the
> dark-theme SVGs and `<picture>` tags in this plan were dropped (PR #1); figures are light only.
> The spec is the current description.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 12 default-matplotlib PNG charts with 13 figures plus a hero in one house style
(light and dark SVG, Inter font, finding-first titles), rendered by a new `ulpe figures` command from
committed `results/`, and reorder the README into a story.

**Architecture:** The analysis commands stop drawing and write the few extra tables the figures
need to `results/figure_data/`. A new package `src/uniswap_lp_economics/viz/` holds the style
(`style.py`), the results loader (`data.py`), the registry and command (`render.py`), and one module
per story chapter. `ulpe figures` reads only `results/` and renders every figure in seconds;
`ulpe all` runs it last.

**Tech Stack:** Python 3.13, polars, numpy, matplotlib (Agg, SVG, Pillow writer for the GIF), uv,
pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-15-chart-redesign-design.md`

## Global Constraints

- Branch `chart-redesign` off `main`; commit after every task; push to the private repo
  `samuraixx-key/uniswap-lp-economics` without asking. Never add "Co-Authored-By" or any AI
  attribution to commits or PRs.
- Never read `.env`; never print, log or put `ETH_RPC_URL` in messages. No BigQuery query runs in
  this plan (`ulpe analyze`, `ulpe lp` and `ulpe figures` are offline).
- **The Inter download (Task 1, Step 1) needs the user's explicit OK in chat first**, stating the file
  name, source URL and size. Subagents must not download it; the controller does, after the OK.
- Never use the word "toxicity" anywhere.
- Every number in a figure's title or subtitle is formatted from the data at render time.
- Figure canvas 10 × 6.2 in; colours only from `style.Palette` tokens; font Inter, registered from
  `assets/fonts/`, never a fallback.
- SVG output: `svg.fonttype = "path"`, `svg.hashsalt` fixed, no `Date` metadata; rendering the same
  inputs twice gives identical bytes.
- Line length 100 (ruff); `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`
  and `uv run pytest -q` all pass at the end of every task.

## Review Focus

1. **A group is missing from the results** (no JIT position, no vault, a single flow label): every
   figure still renders and leaves the group out; figure 11 says there is no JIT position. Tests:
   Task 6 (single flow label), Task 9 (no JIT, no vault), Task 10 (empty `jit_block`).
2. **Zero or negative values on a log axis** (a day with zero LVR in figure 5, a position worth $0
   in figure 9): those points are dropped from that axis and the figure renders. Tests: Tasks 7, 9.
3. **Searchers' kept is positive, or a destination flow is negative**: the Sankey still balances
   (sources = destinations) and draws. Test: Task 11.
4. **Stale figure files** from an earlier render (the 12 old PNGs, a renamed stem): `ulpe figures`
   deletes figure files in `results/figures/` that it did not write. Test: Task 4.
5. **A results directory from before this change** (no `figure_data/`, a `summary.json` without
   `lp.daily`): `ulpe figures` stops and names the missing file or key and the command that writes
   it. Test: Task 4.

---

## File structure

| File | Responsibility |
|---|---|
| `assets/fonts/Inter-{Regular,SemiBold,Bold}.ttf`, `assets/fonts/LICENSE.txt` | Bundled font (SIL OFL) |
| `src/uniswap_lp_economics/viz/__init__.py` | Package marker |
| `src/uniswap_lp_economics/viz/style.py` | Palettes, `theme()`, `pal()`, `new_figure()`, `frame()`, formatters, `fade_band()`, `no_data()`, `save_svg()`, `svg_bytes()` |
| `src/uniswap_lp_economics/viz/data.py` | `Results` and `load_results()` with clear missing-input errors |
| `src/uniswap_lp_economics/viz/render.py` | `FIGURES`, `EXTRAS`, `render_all()`, `run_figures()` |
| `src/uniswap_lp_economics/viz/what_is_lvr.py` | Figure 1 (concept), figure 2 (episode), the GIF |
| `src/uniswap_lp_economics/viz/discovery.py` | Figure 3 |
| `src/uniswap_lp_economics/viz/markouts.py` | Figure 4 |
| `src/uniswap_lp_economics/viz/fees_vs_lvr.py` | Figures 5, 6, 7 |
| `src/uniswap_lp_economics/viz/bots.py` | Figure 8 |
| `src/uniswap_lp_economics/viz/who_pays.py` | Figures 9, 10, 12 |
| `src/uniswap_lp_economics/viz/jit_block.py` | Figure 11 |
| `src/uniswap_lp_economics/viz/hero.py` | Hero Sankey and the social card |
| `src/uniswap_lp_economics/lp/figdata.py` | Episode and JIT-block selection and tables |
| `src/uniswap_lp_economics/discovery.py` (modify) | `basis_histogram()` |
| `src/uniswap_lp_economics/analyze.py`, `lp/analyze.py` (modify) | Write figure data; stop drawing |
| `src/uniswap_lp_economics/figures.py`, `lp/figures.py` (delete) | Replaced by `viz/` |
| `src/uniswap_lp_economics/cli.py` (modify) | `ulpe figures`; `figures` last in `ALL_STEPS` |
| `tests/vizfix.py` | Fixture `results/` directory for the figure tests |
| `tests/test_viz_*.py`, `tests/test_figdata.py` | Tests |

---

### Task 1: Font and house style

**Files:**
- Create: `assets/fonts/Inter-Regular.ttf`, `assets/fonts/Inter-SemiBold.ttf`, `assets/fonts/Inter-Bold.ttf`, `assets/fonts/LICENSE.txt`
- Create: `src/uniswap_lp_economics/viz/__init__.py`, `src/uniswap_lp_economics/viz/style.py`
- Test: `tests/test_viz_style.py`

**Interfaces:**
- Produces: `MODES = ("light", "dark")`, `CANVAS = (10.0, 6.2)`, `Palette` (frozen dataclass,
  fields `background ink muted faint grid lvr fees jit other protocol builder proposer searcher
  binance`, all `str`), `PALETTES: dict[str, Palette]`, `theme(mode: str) -> ContextManager[Palette]`,
  `pal() -> Palette`, `new_figure(nrows=1, ncols=1, *, size=CANVAS, left=0.085, right=0.97,
  top=0.80, bottom=0.15, wspace=None, **subplot_kw) -> tuple[Figure, Any]`,
  `frame(fig, title, subtitle, source) -> None`, `usd(x: float) -> str`, `pct(x: float) -> str`,
  `USD_FMT: FuncFormatter`, `per_10k_month(bp_per_day: float) -> float`,
  `fade_band(ax, x, lo, hi, color, layers=4, alpha=0.30) -> None`, `no_data(ax, text="no data")`,
  `save_svg(fig, path) -> None`, `svg_bytes(fig) -> bytes`, `register_fonts() -> None`,
  `FONT_DIR: Path`.

- [ ] **Step 1: Download Inter (controller only, after the user's OK)**

Ask the user first: "Download `Inter-4.1.zip` (about 10 MB) from
`https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip` and commit three static TTFs and
the licence to `assets/fonts/`?" After the OK:

```bash
cd "/c/ABC/DeFI Test/uniswap-lp-economics"
TMP="$(mktemp -d)"
curl -sSL -o "$TMP/inter.zip" https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip
unzip -l "$TMP/inter.zip" | grep -E "Inter-(Regular|SemiBold|Bold)\.ttf|LICENSE"
mkdir -p assets/fonts
unzip -j -o "$TMP/inter.zip" "extras/ttf/Inter-Regular.ttf" "extras/ttf/Inter-SemiBold.ttf" "extras/ttf/Inter-Bold.ttf" "LICENSE.txt" -d assets/fonts
ls -la assets/fonts
```

Expected: the four files in `assets/fonts/`. If the listing shows other paths for the static TTFs,
use those paths in the `unzip -j` line.

- [ ] **Step 2: Write the failing tests**

`tests/test_viz_style.py`:

```python
from pathlib import Path

import matplotlib.pyplot as plt
import pytest

from uniswap_lp_economics.viz import style


def test_usd_formats_like_the_readme() -> None:
    assert style.usd(1_097_836.3) == "$1.1M"
    assert style.usd(-201_569.9) == "−$202k"
    assert style.usd(3_562.6) == "$3.6k"
    assert style.usd(40.4) == "$40"
    assert style.usd(-0.2) == "$0"  # no minus sign on a value that rounds to zero
    assert style.pct(0.4772) == "48%"
    assert style.per_10k_month(-1.35) == pytest.approx(-40.5)


def test_both_palettes_define_every_token() -> None:
    fields = set(style.Palette.__dataclass_fields__)
    for mode in style.MODES:
        p = style.PALETTES[mode]
        assert {f for f in fields if getattr(p, f).startswith("#")} == fields


def test_theme_sets_inter_and_the_palette() -> None:
    with style.theme("dark") as p:
        assert style.pal() is p is style.PALETTES["dark"]
        assert plt.rcParams["font.family"] == ["Inter"]
        assert plt.rcParams["svg.fonttype"] == "path"
    with pytest.raises(RuntimeError, match="theme"):
        style.pal()
    with pytest.raises(ValueError, match="mode"):
        with style.theme("sepia"):
            pass


def test_missing_font_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(style, "FONT_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="Inter-Regular.ttf"):
        style.register_fonts()


def test_svg_is_deterministic_and_undated() -> None:
    def draw() -> bytes:
        with style.theme("light"):
            fig, ax = style.new_figure()
            ax.plot([0, 1], [0, 1])
            style.frame(fig, "Title", "Subtitle", "Source")
            return style.svg_bytes(fig)

    a, b = draw(), draw()
    assert a == b
    assert b"<dc:date>" not in a and a.startswith(b"<?xml")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_viz_style.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'uniswap_lp_economics.viz'`.

- [ ] **Step 4: Write the implementation**

`src/uniswap_lp_economics/viz/__init__.py`:

```python
"""Figures for the README (chart redesign spec): style, results loader, one module per chapter."""
```

`src/uniswap_lp_economics/viz/style.py`:

```python
"""House style for every figure (chart redesign spec sections 5 and 7): palettes for light and dark
mode, the bundled Inter font, the title block, formatters and deterministic SVG output."""

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
    with plt.rc_context(_rc(p)):
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


def frame(fig: Figure, title: str, subtitle: str, source: str) -> None:
    """Headline stating the finding, a muted subtitle with the key numbers, a source line."""
    p = pal()
    fig.text(0.012, 0.975, title, fontsize=15.5, fontweight="bold", va="top", color=p.ink)
    fig.text(0.012, 0.92, subtitle, fontsize=10.5, va="top", color=p.muted)
    fig.text(0.012, 0.012, source, fontsize=8.3, va="bottom", color=p.faint)


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
            xs, mid - (mid - lows) * f, mid + (highs - mid) * f, color=color,
            alpha=alpha / layers, lw=0,
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_viz_style.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: 5 passed; ruff and mypy clean. (Run `uv run ruff format .` first if the format check
fails.)

- [ ] **Step 6: Commit**

```bash
git add assets/fonts src/uniswap_lp_economics/viz tests/test_viz_style.py
git commit -m "viz: house style (palettes, Inter, title block, deterministic SVG)"
git push -q origin chart-redesign
```

---

### Task 2: `ulpe analyze` writes the basis histogram and stops drawing

**Files:**
- Modify: `src/uniswap_lp_economics/discovery.py` (add `basis_histogram`)
- Modify: `src/uniswap_lp_economics/analyze.py` (remove `FIGURES`, the `figures` import and the six
  `figures.*` calls; write `figure_data/basis_hist.csv`)
- Test: `tests/test_discovery.py`, `tests/test_analyze.py`

**Interfaces:**
- Produces: `discovery.basis_histogram(series: pl.DataFrame) -> pl.DataFrame` with columns
  `bin_lo_bp: Float64, bin_hi_bp: Float64, blocks: Int64` (200 bins of 0.5 bp over [−50, 50] bp,
  values outside clipped into the edge bins); file `results/figure_data/basis_hist.csv`.
- Consumes: `discovery.FEE_BAND_BP`, `series["basis_bp"]` (existing).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_discovery.py`:

```python
def test_basis_histogram_bins_and_clips() -> None:
    series = pl.DataFrame({"basis_bp": [0.1, 0.2, -0.3, 80.0, -90.0, None, float("nan")]})
    h = discovery.basis_histogram(series)
    assert h.columns == ["bin_lo_bp", "bin_hi_bp", "blocks"]
    assert h.height == 200 and h["bin_lo_bp"][0] == -50.0 and h["bin_hi_bp"][-1] == 50.0
    assert int(h["blocks"].sum()) == 5  # null and NaN dropped; ±80/90 clipped into the edges
    assert int(h["blocks"][0]) == 1 and int(h["blocks"][-1]) == 1
    zero = h.filter((pl.col("bin_lo_bp") == 0.0)).row(0, named=True)
    assert zero["blocks"] == 2  # 0.1 and 0.2 fall in [0, 0.5)
```

In `tests/test_analyze.py`, in `test_analyze_fixture_end_to_end`, replace

```python
    assert len(list((results / "figures").glob("*.png"))) == 6
```

with

```python
    assert not (results / "figures").exists()  # `ulpe figures` draws; analyze writes data only
    hist = pl.read_csv(results / "figure_data" / "basis_hist.csv")
    assert hist.columns == ["bin_lo_bp", "bin_hi_bp", "blocks"] and hist.height == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_discovery.py tests/test_analyze.py -q`
Expected: FAIL (`basis_histogram` missing; figures directory still written).

- [ ] **Step 3: Write the implementation**

In `src/uniswap_lp_economics/discovery.py` add (with `import numpy as np` if absent):

```python
BASIS_HIST_RANGE_BP = 50.0
BASIS_HIST_BINS = 200


def basis_histogram(series: pl.DataFrame) -> pl.DataFrame:
    """Counts of the block-start basis in 0.5 bp bins over [-50, 50] bp, for figure 3. Values
    outside the range are clipped into the edge bins; null and NaN are dropped."""
    b = series["basis_bp"].drop_nulls().drop_nans().clip(
        -BASIS_HIST_RANGE_BP, BASIS_HIST_RANGE_BP
    ).to_numpy()
    edges = np.linspace(-BASIS_HIST_RANGE_BP, BASIS_HIST_RANGE_BP, BASIS_HIST_BINS + 1)
    counts, _ = np.histogram(b, bins=edges)
    return pl.DataFrame(
        {"bin_lo_bp": edges[:-1], "bin_hi_bp": edges[1:], "blocks": counts.astype(np.int64)}
    )
```

In `src/uniswap_lp_economics/analyze.py`:
1. Delete the `FIGURES = {...}` dict and `figures` from the `from uniswap_lp_economics import (...)`
   list.
2. Delete `figs = out / "figures"` and the six lines calling `figures.markout_curves`,
   `figures.basis_histogram`, `figures.episode_chart`, `figures.cross_correlation_chart`,
   `figures.waterfall_chart`, `figures.bot_profit_chart`.
3. Where `figures.basis_histogram(...)` was, write:

```python
    fig_data = out / "figure_data"
    fig_data.mkdir(parents=True, exist_ok=True)
    write_text_atomic(fig_data / "basis_hist.csv", discovery.basis_histogram(series).write_csv())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`
Expected: all pass. (`figures.py` and `tests/test_figures.py` still exist; `lp/figures.py` imports
helpers from `figures.py`. Both are deleted in Task 3.)

- [ ] **Step 5: Commit**

```bash
git add src/uniswap_lp_economics/discovery.py src/uniswap_lp_economics/analyze.py tests/test_discovery.py tests/test_analyze.py
git commit -m "analyze: write figure_data/basis_hist.csv instead of drawing"
git push -q origin chart-redesign
```

---

### Task 3: `ulpe lp` writes the episode and JIT-block tables and stops drawing

**Files:**
- Create: `src/uniswap_lp_economics/lp/figdata.py`
- Modify: `src/uniswap_lp_economics/lp/analyze.py` (remove `LP_FIGURES`, the `figures` import and
  the six `figures.*` calls; compute and write three figure-data files)
- Delete: `src/uniswap_lp_economics/figures.py`, `src/uniswap_lp_economics/lp/figures.py`,
  `tests/test_figures.py`, `tests/test_lp_figures.py`
- Test: `tests/test_figdata.py`, `tests/test_lp_analyze.py`

**Interfaces:**
- Produces:
  - `figdata.episode_window(daily: pl.DataFrame, blocks_state: pl.DataFrame) -> pl.DataFrame`
    (rows of `blocks_state`, sorted by block).
  - `figdata.episode_tables(daily, blocks_state, steps, trades) -> tuple[pl.DataFrame, pl.DataFrame]`:
    blocks table with columns `block_number: Int64, ts_us: Int64, pool_price: Float64,
    p_cex: Float64, lvr_0_usd: Float64, has_searcher: Boolean`; Binance table `ts_us: Int64,
    price: Float64` (last trade each second).
  - `figdata.select_jit_position(positions, flows_window, swaps) -> tuple[str | None, bool]`.
  - `figdata.jit_block_table(positions, flows_window, swaps, events, steps, blocks_state) -> pl.DataFrame`
    with `JIT_BLOCK_SCHEMA` (below).
  - Files `results/figure_data/episode_blocks.csv`, `episode_cex.csv`, `jit_block.csv`.
- Consumes: `v3math.sqrt_price_x96_to_eth_price`, `config.BLOCK_TIME_S`, `config.US`.

- [ ] **Step 1: Write the failing tests**

`tests/test_figdata.py`:

```python
from datetime import UTC, date, datetime

import polars as pl
import pytest

from uniswap_lp_economics.lp import figdata
from uniswap_lp_economics.v3math import Q96

US = 1_000_000


def ts(day: int, second: int) -> int:
    return int(datetime(2026, 7, day, tzinfo=UTC).timestamp()) * US + second * US


def test_episode_window_picks_the_biggest_move_on_the_worst_day() -> None:
    daily = pl.DataFrame({"day": [date(2026, 7, 1), date(2026, 7, 2)], "lvr_0": [5.0, 9.0]})
    n = 60
    prices = [2000.0] * 30 + [2000.0 + 10 * k for k in range(1, 21)] + [2200.0] * 10
    state = pl.DataFrame(
        {
            "block_number": list(range(100, 100 + n)) + [500],
            "ts_us": [ts(2, 12 * i) for i in range(n)] + [ts(1, 0)],
            "p_cex": prices + [1.0],
        }
    )
    w = figdata.episode_window(daily, state)
    assert w.height == 32
    assert w["block_number"][0] == 100 + 29 - 4  # the 20-block move starts at block 129 (i0 = 29)
    assert 500 not in w["block_number"].to_list()  # other days are ignored


def test_episode_tables_price_lvr_and_binance_seconds() -> None:
    daily = pl.DataFrame({"day": [date(2026, 7, 2)], "lvr_0": [1.0]})
    sqrt = int(Q96 * (1e12 / 2000.0) ** 0.5)  # pool price 2000 USD per ETH
    state = pl.DataFrame(
        {
            "block_number": [1, 2, 3],
            "ts_us": [ts(2, 0), ts(2, 12), ts(2, 24)],
            "p_cex": [2000.0, 2010.0, 2020.0],
            "end_sqrt_price_x96": [sqrt, sqrt, sqrt],
        },
        schema_overrides={"end_sqrt_price_x96": pl.Int128},
    )
    steps = pl.DataFrame(
        {"block_number": [2, 2, 3], "lvr_0": [3.0, 4.0, -1.0], "flow_label": ["searcher", "x", "x"]}
    )
    trades = pl.DataFrame(
        {"ts_us": [ts(2, 0) + 100, ts(2, 0) + 900_000, ts(2, 5), ts(2, 99)], "price": [1.0, 2.0, 3.0, 9.0]}
    )
    blocks, cex = figdata.episode_tables(daily, state, steps, trades)
    assert blocks["pool_price"][0] == pytest.approx(2000.0, rel=1e-9)
    assert blocks["lvr_0_usd"].to_list() == [0.0, 7.0, -1.0]
    assert blocks["has_searcher"].to_list() == [False, True, False]
    assert cex.rows() == [(ts(2, 0), 2.0), (ts(2, 5), 3.0)]  # last trade per second; 99 s is past the end


def _jit_inputs(full: bool) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    positions = pl.DataFrame(
        {
            "position_id": ["j1", "j2", "w"],
            "lp_type": ["jit", "jit", "nft_wallet"],
            "pnl_rebal_usd": [50.0, 10.0, 999.0],
            "start_block": [7, 8, 7],
        }
    )
    flows = pl.DataFrame(
        {
            "position_id": ["j1", "j1", "j2", "j2"],
            "block_number": [7, 7, 8, 8],
            "tx_hash": ["a", "b", "c", "c"],
            "pool_log_index": [2, 5, 1, 3],
            "liquidity_delta": [10, -10, 4, -4],
        }
    )
    # j2's transaction c swaps before its add (log 0) and after its removal (log 4); j1's do not
    swaps = pl.DataFrame(
        {
            "tx_hash": ["c", "c", "a", "z"],
            "log_index": [0, 4 if full else 2, 3, 3],
            "block_number": [8, 8, 7, 8],
        }
    )
    return positions, flows, swaps


def test_select_jit_prefers_the_full_pattern_then_falls_back() -> None:
    assert figdata.select_jit_position(*_jit_inputs(full=True)) == ("j2", True)
    assert figdata.select_jit_position(*_jit_inputs(full=False)) == ("j1", False)
    positions, flows, swaps = _jit_inputs(full=True)
    no_jit = positions.filter(pl.col("lp_type") != "jit")
    assert figdata.select_jit_position(no_jit, flows, swaps) == (None, False)


def test_jit_block_table_lists_the_block_in_log_order_with_roles() -> None:
    positions, flows, swaps = _jit_inputs(full=True)
    sqrt = int(Q96 * (1e12 / 2000.0) ** 0.5)
    events = pl.DataFrame(
        {
            "block_number": [8] * 5,
            "log_index": [0, 1, 2, 3, 4],
            "event": ["swap", "mint", "swap", "burn", "swap"],
            "tx_hash": ["c", "c", "z", "c", "c"],
            "amount0": [10**9, 10**9, 2 * 10**9, -(10**9), -(10**9)],
            "amount1": [0, 10**18, 0, -(10**18), 0],
            "sqrt_price_x96": [sqrt, None, sqrt, None, sqrt],
        },
        schema_overrides={"amount0": pl.Int128, "amount1": pl.Int128, "sqrt_price_x96": pl.Int128},
    )
    # the swaps table as aligned.parquet holds it: one row per swap event of the block
    aligned = pl.DataFrame(
        {
            "tx_hash": ["c", "z", "c"],
            "log_index": [0, 2, 4],
            "block_number": [8, 8, 8],
            "notional_usd": [1.0, 2.0, 1.0],
            "markout_usd_0": [-0.5, 0.1, -0.2],
        }
    )
    steps = pl.DataFrame(
        {"block_number": [8, 8], "log_index": [2, 2], "fee_usd": [0.3, 0.1], "lvr_0": [-1.0, -0.5]}
    )
    state = pl.DataFrame(
        {"block_number": [8], "sqrt_price_x96": [sqrt]}, schema_overrides={"sqrt_price_x96": pl.Int128}
    )
    t = figdata.jit_block_table(positions, flows, aligned, events, steps, state)
    assert t.columns == list(figdata.JIT_BLOCK_SCHEMA)
    assert t["role"].to_list() == ["operator", "jit", "other", "jit", "operator"]
    assert t["full_pattern"].unique().to_list() == [True] and t["position_id"][0] == "j2"
    served = t.row(2, named=True)
    assert served["fee_usd"] == pytest.approx(0.4) and served["lvr_0_usd"] == pytest.approx(-1.5)
    assert served["notional_usd"] == 2.0
    assert t["pool_price_after"][1] == pytest.approx(2000.0, rel=1e-9)
    empty = figdata.jit_block_table(
        positions.filter(pl.col("lp_type") != "jit"), flows, aligned, events, steps, state
    )
    assert empty.height == 0 and empty.columns == list(figdata.JIT_BLOCK_SCHEMA)
```

In `tests/test_lp_analyze.py`:
1. Replace the two lines

```python
    for name in lp.LP_FIGURES.values():
        assert (results / "figures" / name).exists(), name
```

with

```python
    fd = results / "figure_data"
    blocks = pl.read_csv(fd / "episode_blocks.csv")
    assert blocks.columns == [
        "block_number", "ts_us", "pool_price", "p_cex", "lvr_0_usd", "has_searcher"
    ]
    assert blocks.height >= 1 and pl.read_csv(fd / "episode_cex.csv").height >= 1
    jit_block = pl.read_csv(fd / "jit_block.csv")
    assert jit_block.height >= 3 and set(jit_block["role"]) >= {"jit"}
    assert jit_block["full_pattern"].to_list()[0] is False  # the world's JIT has no own swaps around it
    assert not (results / "figures").exists()
```

2. Delete `tests/test_figures.py` and `tests/test_lp_figures.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_figdata.py tests/test_lp_analyze.py -q`
Expected: FAIL (`figdata` missing).

- [ ] **Step 3: Write `lp/figdata.py`**

```python
"""Small tables the figures need beyond the results tables (chart redesign spec section 4): the
stale-pool episode of figure 2 and the JIT block of figure 11, each picked by a fixed rule."""

from typing import Any

import numpy as np
import polars as pl

from uniswap_lp_economics.config import BLOCK_TIME_S, US
from uniswap_lp_economics.v3math import sqrt_price_x96_to_eth_price

EPISODE_MOVE_BLOCKS = 20
EPISODE_BEFORE = 4
EPISODE_LENGTH = 32
JIT_BLOCK_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "event": pl.String,
    "role": pl.String,
    "tx_hash": pl.String,
    "amount_usdc": pl.Float64,
    "amount_eth": pl.Float64,
    "pool_price_after": pl.Float64,
    "notional_usd": pl.Float64,
    "markout_usd_0": pl.Float64,
    "fee_usd": pl.Float64,
    "lvr_0_usd": pl.Float64,
    "position_id": pl.String,
    "full_pattern": pl.Boolean,
}


def episode_window(daily: pl.DataFrame, blocks_state: pl.DataFrame) -> pl.DataFrame:
    """On the day with the largest measured LVR (0 s; the earliest such day on ties), the 20-block
    stretch with the largest absolute Binance log move; the window starts 4 blocks before it and
    runs 32 blocks (fewer at the day's edges)."""
    day = daily.sort(["lvr_0", "day"], descending=[True, False])["day"][0]
    bs = (
        blocks_state.sort("block_number")
        .with_columns(_day=pl.from_epoch("ts_us", time_unit="us").dt.date())
        .filter(pl.col("_day") == day)
        .drop("_day")
    )
    if bs.height == 0:
        raise ValueError(f"no blocks on {day}, the day with the largest LVR")
    logp = np.log(bs["p_cex"].to_numpy().astype(float))
    w = min(EPISODE_MOVE_BLOCKS, bs.height - 1)
    i0 = 0
    if w > 0:
        move = np.nan_to_num(np.abs(logp[w:] - logp[:-w]), nan=-1.0)
        i0 = int(np.argmax(move))
    return bs.slice(max(i0 - EPISODE_BEFORE, 0), EPISODE_LENGTH)


def episode_tables(
    daily: pl.DataFrame, blocks_state: pl.DataFrame, steps: pl.DataFrame, trades: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Figure 2's data: per block of the window, the pool price after the block, Binance at block
    time, LVR (0 s) over the block's steps and whether a searcher swapped; and Binance's last trade
    in each second of the window."""
    win = episode_window(daily, blocks_state)
    per_block = (
        steps.filter(pl.col("block_number").is_in(win["block_number"].implode()))
        .group_by("block_number")
        .agg(
            lvr_0_usd=pl.col("lvr_0").sum(),
            has_searcher=(pl.col("flow_label") == "searcher").any(),
        )
    )
    prices = [sqrt_price_x96_to_eth_price(int(s)) for s in win["end_sqrt_price_x96"].to_list()]
    blocks = (
        win.select("block_number", "ts_us", "p_cex")
        .with_columns(pool_price=pl.Series(prices, dtype=pl.Float64))
        .join(per_block, on="block_number", how="left")
        .with_columns(pl.col("lvr_0_usd").fill_null(0.0), pl.col("has_searcher").fill_null(False))
        .select("block_number", "ts_us", "pool_price", "p_cex", "lvr_0_usd", "has_searcher")
        .sort("block_number")
    )
    t0 = int(win["ts_us"][0])
    t1 = int(win["ts_us"][-1]) + BLOCK_TIME_S * US
    cex = (
        trades.filter((pl.col("ts_us") >= t0) & (pl.col("ts_us") < t1))
        .sort("ts_us")
        .group_by((pl.col("ts_us") // US).alias("sec"), maintain_order=True)
        .agg(pl.col("price").last())
        .select(ts_us=pl.col("sec") * US, price=pl.col("price").cast(pl.Float64))
        .sort("ts_us")
    )
    return blocks, cex


def select_jit_position(
    positions: pl.DataFrame, flows_window: pl.DataFrame, swaps: pl.DataFrame
) -> tuple[str | None, bool]:
    """Figure 11's position: among JIT positions whose own transactions also swap in the pool both
    before the first add and after the last removal, the one with the largest P&L vs rebalancing
    (then lowest block, then id). Without such a position, the most profitable JIT position, with
    the flag False; without JIT positions, (None, False)."""
    jit = positions.filter(pl.col("lp_type") == "jit").select(
        "position_id", "pnl_rebal_usd", "start_block"
    )
    if jit.height == 0:
        return None, False
    f = flows_window.join(jit.select("position_id"), on="position_id", how="semi")
    span = f.group_by("position_id").agg(
        first_add=pl.col("pool_log_index").filter(pl.col("liquidity_delta") > 0).min(),
        last_remove=pl.col("pool_log_index").filter(pl.col("liquidity_delta") < 0).max(),
    )
    own = (
        f.select("position_id", "tx_hash", "block_number")
        .unique()
        .join(swaps.select("tx_hash", "log_index", "block_number"), on=["tx_hash", "block_number"])
    )
    pattern = (
        own.join(span, on="position_id")
        .group_by("position_id")
        .agg(
            before=(pl.col("log_index") < pl.col("first_add")).any(),
            after=(pl.col("log_index") > pl.col("last_remove")).any(),
        )
        .filter(pl.col("before") & pl.col("after"))
    )
    full = jit.join(pattern.select("position_id"), on="position_id", how="semi")
    pool, flag = (full, True) if full.height else (jit, False)
    best = pool.sort(
        ["pnl_rebal_usd", "start_block", "position_id"], descending=[True, False, False]
    ).row(0, named=True)
    return str(best["position_id"]), flag


def jit_block_table(
    positions: pl.DataFrame,
    flows_window: pl.DataFrame,
    swaps: pl.DataFrame,
    events: pl.DataFrame,
    steps: pl.DataFrame,
    blocks_state: pl.DataFrame,
) -> pl.DataFrame:
    """Figure 11's data: every pool event of the selected JIT position's block in log order, with
    its role (`jit` = the position's own liquidity events, `operator` = other events in the
    position's transactions, `other`), the pool price after it and the swaps' USD flows."""
    pid, full = select_jit_position(positions, flows_window, swaps)
    if pid is None:
        return pl.DataFrame(schema=JIT_BLOCK_SCHEMA)
    f = flows_window.filter(pl.col("position_id") == pid)
    block = int(f["block_number"][0])
    txs = set(f["tx_hash"].to_list())
    own_logs = set(f["pool_log_index"].to_list())
    start = blocks_state.filter(pl.col("block_number") == block)["sqrt_price_x96"][0]
    price = sqrt_price_x96_to_eth_price(int(start))
    rows = []
    for e in events.filter(pl.col("block_number") == block).sort("log_index").iter_rows(named=True):
        if e["event"] == "swap" and e["sqrt_price_x96"] is not None:
            price = sqrt_price_x96_to_eth_price(int(e["sqrt_price_x96"]))
        role = "jit" if e["log_index"] in own_logs else "operator" if e["tx_hash"] in txs else "other"
        rows.append(
            {
                "block_number": block,
                "log_index": e["log_index"],
                "event": e["event"],
                "role": role,
                "tx_hash": e["tx_hash"],
                "amount_usdc": int(e["amount0"] or 0) / 1e6,
                "amount_eth": int(e["amount1"] or 0) / 1e18,
                "pool_price_after": price,
                "position_id": pid,
                "full_pattern": full,
            }
        )
    base = pl.DataFrame(rows).with_columns(pl.col("log_index").cast(pl.Int64))
    sw = swaps.filter(pl.col("block_number") == block).select(
        pl.col("log_index").cast(pl.Int64), "notional_usd", "markout_usd_0"
    )
    st = (
        steps.filter(pl.col("block_number") == block)
        .group_by(pl.col("log_index").cast(pl.Int64))
        .agg(fee_usd=pl.col("fee_usd").sum(), lvr_0_usd=pl.col("lvr_0").sum())
    )
    out = base.join(sw, on="log_index", how="left").join(st, on="log_index", how="left")
    return out.select(list(JIT_BLOCK_SCHEMA)).cast(JIT_BLOCK_SCHEMA).sort("log_index")
```

- [ ] **Step 4: Wire it into `lp/analyze.py` and delete the old figure code**

In `src/uniswap_lp_economics/lp/analyze.py`:
1. Change `from uniswap_lp_economics.lp import destination, figures, lifetime, pnl, theory` to
   `from uniswap_lp_economics.lp import destination, figdata, lifetime, pnl, theory`.
2. Delete the `LP_FIGURES = {...}` dict.
3. Before the comment `# Everything is computed: write the checks, ...`, add:

```python
    episode_blocks, episode_cex = figdata.episode_tables(daily, bs, steps, inp.trades)
    jit_block = figdata.jit_block_table(
        positions, flows_window, inp.aligned, inp.events, steps, bs
    )
```

4. Replace the block from `figs = out / "figures"` through
   `figures.destination_waterfall(dest, figs / LP_FIGURES["destination"])` with:

```python
    fig_data = out / "figure_data"
    fig_data.mkdir(parents=True, exist_ok=True)
    write_text_atomic(fig_data / "episode_blocks.csv", episode_blocks.write_csv())
    write_text_atomic(fig_data / "episode_cex.csv", episode_cex.write_csv())
    write_text_atomic(fig_data / "jit_block.csv", jit_block.write_csv())
```

5. Delete `src/uniswap_lp_economics/figures.py`, `src/uniswap_lp_economics/lp/figures.py`.
6. `grep -rn "figures" src tests` and remove any remaining reference to the deleted modules (the
   `report` and `cli` modules do not import them).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "lp: write the episode and JIT-block figure data; drop the old figure modules"
git push -q origin chart-redesign
```

---

### Task 4: Results loader, registry and `ulpe figures`

**Files:**
- Create: `src/uniswap_lp_economics/viz/data.py`, `src/uniswap_lp_economics/viz/render.py`
- Create: `tests/vizfix.py`, `tests/test_viz_render.py`
- Modify: `src/uniswap_lp_economics/cli.py` (subcommand `figures`; `"figures"` last in `ALL_STEPS`;
  `run_step("figures")`)
- Modify: `tests/test_cli_all.py`

**Interfaces:**
- Produces:
  - `data.Results` (frozen dataclass): `summary: dict[str, Any]`, `markouts`, `bot_profit`,
    `episodes`, `basis_hist`, `daily`, `positions`, `groups`, `episode_blocks`, `episode_cex`,
    `jit_block` (all `pl.DataFrame`; `daily["day"]` parsed as `Date`).
  - `data.load_results(results_dir: Path) -> Results`; raises `FileNotFoundError` whose message
    names every missing file or summary key and the `ulpe` command that writes it.
  - `render.FigureFn = Callable[[Results], Figure]`, `render.ExtraFn = Callable[[Results, Path], list[Path]]`,
    `render.FIGURES: list[tuple[str, FigureFn]]`, `render.EXTRAS: list[ExtraFn]`,
    `render.render_all(results_dir: Path, out_dir: Path, preview_dir: Path | None = None) -> list[Path]`,
    `render.run_figures() -> str`.
  - `tests/vizfix.py`: `fixture_frames() -> dict[str, Any]`, `write_results(d: Path, frames: dict[str, Any]) -> Path`.

- [ ] **Step 1: Write the fixture module**

`tests/vizfix.py`:

```python
"""A small results/ directory with every file the figures read (chart redesign spec section 3)."""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

US = 1_000_000
T0 = 1_787_000_000 * US


def fixture_frames() -> dict[str, Any]:
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(6)]
    sigma = [0.2, 0.3, 0.4, 0.5, 0.7, 1.0]
    daily = pl.DataFrame(
        {
            "day": days,
            "fees_usd": [10.0, 14.0, 18.0, 22.0, 30.0, 45.0],
            "protocol_fee_usd": [3.0, 4.0, 6.0, 7.0, 10.0, 15.0],
            "lvr_0": [8.0, 14.0, 22.0, 30.0, 50.0, 95.0],
            "lvr_12": [9.0, 15.0, 24.0, 33.0, 55.0, 99.0],
            "lvr_0_searcher": [9.0, 16.0, 25.0, 34.0, 55.0, 100.0],
            "fees_searcher": [5.0, 7.0, 9.0, 11.0, 15.0, 22.0],
            "protocol_fees_searcher": [1.5, 2.0, 3.0, 3.5, 5.0, 7.0],
            "rv_1s": [s * s / 365 for s in sigma],
            "sigma_annual": sigma,
            "theory_1s": [7.0, 12.0, 20.0, 27.0, 45.0, 80.0],
            "theory_1m": [9.0, 15.0, 25.0, 33.0, 55.0, 100.0],
            "p_trade": [0.2, 0.25, 0.3, 0.35, 0.4, 0.5],
            "theory_arb": [1.4, 3.0, 6.0, 9.5, 18.0, 40.0],
            "theory_arb_fees": [5.6, 9.0, 14.0, 17.5, 27.0, 40.0],
            "regime": ["low", "low", "mid", "mid", "high", "high"],
        }
    )
    horizons = [0, 12, 60, 300, 3600]
    mk_rows = []
    for grouping, label, base in (("all", None, 0.3), ("flow_label", "searcher", 3.0),
                                  ("flow_label", "aggregator", -6.0)):
        for i, h in enumerate(horizons):
            m = base + 0.2 * i
            mk_rows.append({"grouping": grouping, "flow_label": label, "size_bucket": None,
                            "horizon_s": h, "swaps": 10, "notional_usd": 1e6,
                            "markout_usd": m * 100, "mean_bp": m, "median_bp": m,
                            "ci_lo_bp": m - 1.0, "ci_hi_bp": m + 1.0})
    markouts = pl.DataFrame(mk_rows)
    bot_profit = pl.DataFrame(
        {
            "sender": ["0x" + "a1" * 20, "0x" + "b2" * 20, "TOTAL"],
            "gross_usd": [100.0, 60.0, 160.0],
            "kept_usd": [-10.0, 5.0, -5.0],
        }
    )
    episodes = pl.DataFrame(
        {
            "duration_s": [12.0, 24.0, 36.0, 60.0, 120.0, 12.0],
            "threshold_bp": [5.0, 5.0, 5.0, 5.0, 5.0, 10.0],
            "closer": ["searcher"] * 6,
        }
    )
    edges = [-50.0 + 0.5 * i for i in range(201)]
    basis_hist = pl.DataFrame(
        {
            "bin_lo_bp": edges[:-1],
            "bin_hi_bp": edges[1:],
            "blocks": [max(0, 50 - abs(i - 100)) for i in range(200)],
        }
    )
    positions = pl.DataFrame(
        {
            "position_id": ["j1", "j2", "w1", "w2", "v1", "dust"],
            "lp_type": ["jit", "jit", "nft_wallet", "nft_wallet", "lp_vault", "nft_wallet"],
            "twv_usd": [200_000.0, 150_000.0, 5_000.0, 80_000.0, 30_000.0, 0.5],
            "fee_usd": [10.0, 2.0, 5.0, 60.0, 12.0, 0.0],
            "lvr_0": [-6.0, 12.0, 24.0, 455.0, 70.0, 0.01],
            "gas_usd": [3.0, 3.0, 1.0, 5.0, 2.0, 0.0],
            "direct_usd": [2.0, 2.0, 0.0, 0.0, 0.0, 0.0],
            "pnl_rebal_usd": [11.0, -15.0, -20.0, -400.0, -60.0, -0.01],
        }
    )
    group_rows = []
    for grouping, group, v, lo, hi in (
        ("lp_type", "jit", 900.0, -500.0, 2500.0),
        ("lp_type", "nft_wallet", -1.3, -1.8, -1.1),
        ("lp_type", "lp_vault", -1.6, -3.0, -1.2),
        ("width_bucket", "<50", -6.0, -20.0, 3.0),
        ("width_bucket", ">=5000", -0.7, -0.8, -0.6),
    ):
        group_rows.append({"grouping": grouping, "group": group, "positions": 2, "fees_usd": 1.0,
                           "lvr_0_usd": 1.0, "gas_usd": 0.1, "direct_usd": 0.0,
                           "pnl_rebal_usd": -1.0, "pnl_hold_usd": -2.0, "share_beat_hold": 0.4,
                           "bp_per_day": v, "ci_lo_bp": lo, "ci_hi_bp": hi,
                           "bp_per_day_hold": v})
    groups = pl.DataFrame(group_rows)
    episode_blocks = pl.DataFrame(
        {
            "block_number": [10, 11, 12, 13, 14],
            "ts_us": [T0 + 12 * US * i for i in range(5)],
            "pool_price": [2000.0, 2000.0, 2010.0, 2018.0, 2020.0],
            "p_cex": [2000.0, 2008.0, 2016.0, 2020.0, 2021.0],
            "lvr_0_usd": [0.0, 0.0, 300.0, 250.0, 40.0],
            "has_searcher": [False, False, True, True, True],
        }
    )
    episode_cex = pl.DataFrame(
        {"ts_us": [T0 + US * s for s in range(60)],
         "price": [2000.0 + 21.0 * min(s, 40) / 40 for s in range(60)]}
    )
    jit_block = pl.DataFrame(
        {
            "block_number": [12] * 5,
            "log_index": [0, 1, 2, 3, 4],
            "event": ["swap", "mint", "swap", "burn", "swap"],
            "role": ["operator", "jit", "other", "jit", "operator"],
            "tx_hash": ["c", "c", "z", "c", "c"],
            "amount_usdc": [1000.0, 50_000.0, 20_000.0, -50_000.0, -1000.0],
            "amount_eth": [0.0, 25.0, 0.0, -25.0, 0.0],
            "pool_price_after": [2001.0, 2001.0, 2004.0, 2004.0, 2002.0],
            "notional_usd": [1000.0, None, 20_000.0, None, 1000.0],
            "markout_usd_0": [-2.0, None, -8.0, None, -1.0],
            "fee_usd": [None, None, 10.0, None, None],
            "lvr_0_usd": [None, None, -6.0, None, None],
            "position_id": ["j1"] * 5,
            "full_pattern": [True] * 5,
        }
    )
    summary = {
        "lead_lag": {"cross_correlation": [{"lag_blocks": k, "corr": c, "n": 100}
                                           for k, c in zip(range(-3, 4), [0.0, 0.01, 0.05, 0.2,
                                                                          0.35, 0.1, 0.02])]},
        "arbitrage": {"available_usd": 100.0, "captured_searchers_usd": 80.0,
                      "top_bot_single_pool_gross_usd": 60.0, "gas_burned_usd": 1.0,
                      "priority_fee_usd": 30.0, "coinbase_usd": 35.0, "kept_usd": -6.0},
        "lp": {
            "lp_fees_usd": 139.0, "protocol_fees_usd": 45.0, "lvr_0_usd": 219.0,
            "fees_minus_lvr_usd": -80.0,
            "daily": {"days": 6, "fees_minus_lvr_usd": -80.0, "fees_minus_lvr_ci_lo_usd": -110.0,
                      "fees_minus_lvr_ci_hi_usd": -50.0, "total_fees_usd": 184.0,
                      "total_fees_minus_lvr_usd": -35.0, "total_fees_minus_lvr_ci_lo_usd": -60.0,
                      "total_fees_minus_lvr_ci_hi_usd": 5.0, "days_lvr_above_lp_fees": 4,
                      "days_lvr_above_total_fees": 2},
            "lifetime": {"positions": 6, "n_excluded_carry": 0, "share_beat_hold": 0.5,
                         "median_return": 0.0},
            "lifetime_by_life": [
                {"life_bucket": "<1d", "positions": 3, "share_beat_hold": 0.33,
                 "median_return": 0.0},
                {"life_bucket": ">=180d", "positions": 3, "share_beat_hold": 0.67,
                 "median_return": 0.1},
            ],
            "lifetime_by_width": [
                {"width_bucket": "<50", "positions": 3, "share_beat_hold": 0.4,
                 "median_return": 0.0},
                {"width_bucket": ">=5000", "positions": 3, "share_beat_hold": 0.6,
                 "median_return": 0.01},
            ],
            "destination": {
                "lvr_on_searcher_swaps_usd": 100.0, "fees_on_searcher_swaps_usd": 48.0,
                "protocol_fees_on_searcher_swaps_usd": 16.0, "multi_pool_gross_usd": 6.0,
                "gas_burned_usd": 1.0, "builder_margin_usd": 16.0, "proposer_usd": 19.0,
                "searcher_kept_usd": -6.0, "share_fees": 0.48,
                "sensitivity_self_built": {"proposer_usd": 15.0, "builder_margin_usd": 20.0},
            },
        },
    }
    return {
        "summary": summary, "markouts": markouts, "bot_profit": bot_profit, "episodes": episodes,
        "basis_hist": basis_hist, "daily": daily, "positions": positions, "groups": groups,
        "episode_blocks": episode_blocks, "episode_cex": episode_cex, "jit_block": jit_block,
    }


def write_results(d: Path, frames: dict[str, Any]) -> Path:
    fd = d / "figure_data"
    fd.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(frames["summary"]), encoding="utf-8")
    files = {
        "markouts.csv": frames["markouts"], "bot_profit.csv": frames["bot_profit"],
        "episodes.csv": frames["episodes"], "lvr_daily.csv": frames["daily"],
        "positions.csv": frames["positions"], "lp_groups.csv": frames["groups"],
        "figure_data/basis_hist.csv": frames["basis_hist"],
        "figure_data/episode_blocks.csv": frames["episode_blocks"],
        "figure_data/episode_cex.csv": frames["episode_cex"],
        "figure_data/jit_block.csv": frames["jit_block"],
    }
    for name, df in files.items():
        df.write_csv(d / name)
    return d
```

- [ ] **Step 2: Write the failing tests**

`tests/test_viz_render.py`:

```python
from pathlib import Path

import pytest
from vizfix import fixture_frames, write_results

from uniswap_lp_economics import cli
from uniswap_lp_economics.viz import data, render, style


def test_load_results_reads_every_input(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    assert r.daily["day"].dtype.is_temporal() and r.summary["lp"]["daily"]["days"] == 6
    assert r.jit_block.height == 5 and r.basis_hist.height == 200


def test_missing_inputs_name_the_command(tmp_path: Path) -> None:
    d = write_results(tmp_path, fixture_frames())
    (d / "figure_data" / "jit_block.csv").unlink()
    (d / "markouts.csv").unlink()
    with pytest.raises(FileNotFoundError) as e:
        data.load_results(d)
    msg = str(e.value)
    assert "jit_block.csv missing; run `ulpe lp`" in msg
    assert "markouts.csv missing; run `ulpe analyze`" in msg


def test_old_summary_without_lp_daily_names_the_command(tmp_path: Path) -> None:
    frames = fixture_frames()
    del frames["summary"]["lp"]["daily"]
    with pytest.raises(FileNotFoundError, match=r"lp\.daily.*ulpe lp"):
        data.load_results(write_results(tmp_path, frames))


def test_render_all_writes_both_modes_and_removes_stale_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = write_results(tmp_path / "results", fixture_frames())
    out = d / "figures"
    out.mkdir()
    (out / "7_lp_fees_vs_lvr_daily.png").write_bytes(b"old")
    (out / "notes.txt").write_text("keep")

    def tiny(r: data.Results):  # type: ignore[no-untyped-def]
        fig, ax = style.new_figure()
        ax.plot([0, 1], [0, 1])
        return fig

    monkeypatch.setattr(render, "FIGURES", [("99_tiny", tiny)])
    monkeypatch.setattr(render, "EXTRAS", [])
    written = render.render_all(d, out, preview_dir=tmp_path / "preview")
    assert sorted(p.name for p in written) == ["99_tiny-dark.svg", "99_tiny.svg"]
    assert not (out / "7_lp_fees_vs_lvr_daily.png").exists()  # stale figure file removed
    assert (out / "notes.txt").exists()  # only figure files are cleaned
    assert sorted(p.name for p in (tmp_path / "preview").iterdir()) == [
        "99_tiny-dark.png", "99_tiny.png"
    ]


@pytest.mark.parametrize("stem", [stem for stem, _ in render.FIGURES])
def test_every_figure_renders_deterministically_in_both_modes(tmp_path: Path, stem: str) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    fn = dict(render.FIGURES)[stem]
    for mode in style.MODES:
        with style.theme(mode):
            a = style.svg_bytes(fn(r))
        with style.theme(mode):
            b = style.svg_bytes(fn(r))
        assert a == b and b"<dc:date>" not in a, (stem, mode)


def test_cli_figures_turns_a_missing_input_into_a_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.config, "RESULTS_DIR", tmp_path)
    with pytest.raises(SystemExit, match="ulpe analyze"):
        cli.run_step("figures", False)
```

In `tests/test_cli_all.py`, in `test_all_runs_every_step_in_order`, after `assert ran == list(cli.ALL_STEPS)` add:

```python
    assert ran[-1] == "figures" and ran.index("lp") < ran.index("figures")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_viz_render.py tests/test_cli_all.py -q`
Expected: FAIL (`viz.data` missing).

- [ ] **Step 4: Write `viz/data.py`**

```python
"""Everything the figures read, from results/ only (chart redesign spec sections 2 and 4)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

# results file -> the `ulpe` command that writes it
SOURCES = {
    "summary.json": "analyze",
    "markouts.csv": "analyze",
    "bot_profit.csv": "analyze",
    "episodes.csv": "analyze",
    "figure_data/basis_hist.csv": "analyze",
    "lvr_daily.csv": "lp",
    "positions.csv": "lp",
    "lp_groups.csv": "lp",
    "figure_data/episode_blocks.csv": "lp",
    "figure_data/episode_cex.csv": "lp",
    "figure_data/jit_block.csv": "lp",
}
SUMMARY_KEYS = {"lead_lag": "analyze", "arbitrage": "analyze", "lp": "lp"}
LP_KEYS = ("destination", "daily", "lifetime", "lifetime_by_life", "lifetime_by_width",
           "fees_minus_lvr_usd")


@dataclass(frozen=True)
class Results:
    summary: dict[str, Any]
    markouts: pl.DataFrame
    bot_profit: pl.DataFrame
    episodes: pl.DataFrame
    basis_hist: pl.DataFrame
    daily: pl.DataFrame
    positions: pl.DataFrame
    groups: pl.DataFrame
    episode_blocks: pl.DataFrame
    episode_cex: pl.DataFrame
    jit_block: pl.DataFrame


def load_results(d: Path) -> Results:
    missing = [f"{d / f} missing; run `ulpe {cmd}`" for f, cmd in SOURCES.items()
               if not (d / f).exists()]
    if missing:
        raise FileNotFoundError("; ".join(missing))
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    gaps = [f"summary.json has no {k!r}; run `ulpe {cmd}`" for k, cmd in SUMMARY_KEYS.items()
            if k not in summary]
    gaps += [f"summary.json has no lp.{k}; run `ulpe lp`" for k in LP_KEYS
             if "lp" in summary and k not in summary["lp"]]
    if gaps:
        raise FileNotFoundError("; ".join(gaps))

    def csv(name: str) -> pl.DataFrame:
        return pl.read_csv(d / name, try_parse_dates=True)

    return Results(
        summary=summary,
        markouts=csv("markouts.csv"),
        bot_profit=csv("bot_profit.csv"),
        episodes=csv("episodes.csv"),
        basis_hist=csv("figure_data/basis_hist.csv"),
        daily=csv("lvr_daily.csv"),
        positions=csv("positions.csv"),
        groups=csv("lp_groups.csv"),
        episode_blocks=csv("figure_data/episode_blocks.csv"),
        episode_cex=csv("figure_data/episode_cex.csv"),
        jit_block=csv("figure_data/jit_block.csv"),
    )
```

- [ ] **Step 5: Write `viz/render.py`**

```python
"""The figure registry and `ulpe figures` (chart redesign spec section 3): every figure in light
and dark SVG, plus the extras (GIF, social card); stale figure files are removed."""

from collections.abc import Callable
from pathlib import Path

from matplotlib.figure import Figure

from uniswap_lp_economics import config
from uniswap_lp_economics.viz.data import Results, load_results
from uniswap_lp_economics.viz.style import MODES, save_svg, theme

FigureFn = Callable[[Results], Figure]
ExtraFn = Callable[[Results, Path], list[Path]]

# (file stem, figure function), in README order; each chapter task appends its entries.
FIGURES: list[tuple[str, FigureFn]] = []
EXTRAS: list[ExtraFn] = []
FIGURE_SUFFIXES = {".svg", ".png", ".gif"}
PREVIEW_DPI = 110


def render_all(results_dir: Path, out_dir: Path, preview_dir: Path | None = None) -> list[Path]:
    """Render every figure into out_dir; with preview_dir, also PNG copies for review."""
    r = load_results(results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for stem, fn in FIGURES:
        for mode in MODES:
            name = stem if mode == "light" else f"{stem}-dark"
            with theme(mode):
                fig = fn(r)
                if preview_dir is not None:
                    preview_dir.mkdir(parents=True, exist_ok=True)
                    fig.savefig(preview_dir / f"{name}.png", dpi=PREVIEW_DPI)
                save_svg(fig, out_dir / f"{name}.svg")
            written.append(out_dir / f"{name}.svg")
    for extra in EXTRAS:
        written += extra(r, out_dir)
    for f in out_dir.iterdir():
        if f.suffix in FIGURE_SUFFIXES and f not in written:
            f.unlink()
    return written


def run_figures() -> str:
    written = render_all(config.RESULTS_DIR, config.RESULTS_DIR / "figures")
    print(f"wrote {len(written)} figure files to {config.RESULTS_DIR / 'figures'}")
    return "OK"
```

- [ ] **Step 6: Wire the CLI**

In `src/uniswap_lp_economics/cli.py`:
1. Import: `from uniswap_lp_economics.viz import render as viz_render`.
2. Append `"figures",` as the last entry of `ALL_STEPS` (after `"lp"`).
3. In `run_step`, before the final `else:`, add:

```python
    elif name == "figures":
        try:
            return viz_render.run_figures()
        except FileNotFoundError as e:
            raise SystemExit(str(e)) from None
```

4. Add the parser entry next to `sub.add_parser("lp", ...)`:

```python
    sub.add_parser("figures", help="render results/figures from results/ (light and dark SVG)")
```

5. In the dispatch on `args.command`, add:

```python
    elif args.command == "figures":
        run_step("figures", False)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass (the parametrized figure test collects no cases yet).

- [ ] **Step 8: Commit**

```bash
git add -A src tests
git commit -m "viz: results loader, figure registry and ulpe figures"
git push -q origin chart-redesign
```

---

### Task 5: Chapter "What is LVR?" — figures 1, 2 and the GIF

**Files:**
- Create: `src/uniswap_lp_economics/viz/what_is_lvr.py`
- Modify: `src/uniswap_lp_economics/viz/render.py` (register)
- Test: `tests/test_viz_what_is_lvr.py`

**Interfaces:**
- Consumes: `style.*`, `data.Results` (`episode_blocks`, `episode_cex`).
- Produces: `concept(r) -> Figure`, `episode(r) -> Figure`, `episode_gif(r, out_dir) -> list[Path]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_viz_what_is_lvr.py`:

```python
from pathlib import Path

from PIL import Image
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, render, style, what_is_lvr


def test_registered_in_order() -> None:
    stems = [s for s, _ in render.FIGURES]
    assert stems.index("01_what_is_lvr") < stems.index("02_stale_pool_episode")
    assert what_is_lvr.episode_gif in render.EXTRAS


def test_episode_subtitle_reports_the_window_lvr(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = what_is_lvr.episode(r)
        texts = " ".join(t.get_text() for t in fig.texts)
    assert "5 blocks" in texts and "$590" in texts  # 300 + 250 + 40


def test_gif_has_one_frame_per_block(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path / "r", fixture_frames()))
    [path] = what_is_lvr.episode_gif(r, tmp_path / "out")
    assert path.name == "02_stale_pool_episode.gif"
    assert Image.open(path).n_frames == 5


def test_empty_episode_renders_and_skips_the_gif(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["episode_blocks"] = frames["episode_blocks"].head(0)
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("dark"):
        style.svg_bytes(what_is_lvr.episode(r))
    assert what_is_lvr.episode_gif(r, tmp_path / "out") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_viz_what_is_lvr.py -q`
Expected: FAIL (`what_is_lvr` missing).

- [ ] **Step 3: Write `viz/what_is_lvr.py`**

```python
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
    ("3  An arbitrageur trades", "In that block, a bot buys ETH from\nthe pool at the old, cheaper price."),
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
    ax.scatter(bt[arb], pool[arb], s=28 + lvr[arb] / 40, color=p.lvr, edgecolor=p.background,
               lw=0.8, zorder=5)
    ranked = [int(i) for i in np.argsort(-np.where(arb, lvr, -np.inf))[:4] if arb[i]]
    for rank, i in enumerate(ranked):
        ax.annotate(
            f"arb takes {usd(lvr[i])}", (bt[i], pool[i]),
            xytext=(-14, 14) if rank == 0 else (10, -16), textcoords="offset points",
            fontsize=9.5, color=p.lvr, fontweight="bold", ha="right" if rank == 0 else "left",
        )
    lo = min(pool_all.min(), cp_all.min() if len(cp_all) else pool_all.min())
    hi = max(pool_all.max(), cp_all.max() if len(cp_all) else pool_all.max())
    pad = (hi - lo) * 0.06 or 1.0
    ax.set_xlim(0, bt_all[-1] + BLOCK_TIME_S)
    ax.set_ylim(lo - pad, hi + pad)
    ax.text(0.01, 0.97, "Binance (each second)", transform=ax.transAxes, color=p.binance,
            fontsize=9.5, va="top")
    ax.text(0.01, 0.92, "Uniswap pool (per block)", transform=ax.transAxes, color=p.fees,
            fontsize=9.5, va="top")
    ax.text(0.99, 0.04, "shaded gap = how stale the pool is;\neach block's arbitrage closes it,\n"
            "and the LPs pay the difference (LVR)", transform=ax.transAxes, ha="right",
            va="bottom", fontsize=9.5, color=p.muted)
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
```

- [ ] **Step 4: Register**

In `viz/render.py`, add `from uniswap_lp_economics.viz import what_is_lvr` and set:

```python
FIGURES: list[tuple[str, FigureFn]] = [
    ("01_what_is_lvr", what_is_lvr.concept),
    ("02_stale_pool_episode", what_is_lvr.episode),
]
EXTRAS: list[ExtraFn] = [what_is_lvr.episode_gif]
```

(Import inside `render.py` after the `style` imports; `what_is_lvr` does not import `render`, so
there is no cycle.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass, including the parametrized determinism test for both stems.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "viz: concept diagram, stale-pool episode and its GIF"
git push -q origin chart-redesign
```

---

### Task 6: Sub-project 2 chapters — figures 3 and 4

**Files:**
- Create: `src/uniswap_lp_economics/viz/discovery.py`, `src/uniswap_lp_economics/viz/markouts.py`
- Modify: `src/uniswap_lp_economics/viz/render.py`
- Test: `tests/test_viz_discovery_markouts.py`

**Interfaces:**
- Consumes: `r.basis_hist`, `r.episodes`, `r.summary["lead_lag"]["cross_correlation"]`,
  `r.markouts`; `discovery.FEE_BAND_BP`, `discovery.EPISODE_THRESHOLDS_BP`, `config.HORIZONS_S`.
- Produces: `discovery.pool_follows_binance(r) -> Figure`, `markouts.markouts(r) -> Figure`,
  `markouts.FLOW_NAMES: dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_viz_discovery_markouts.py`:

```python
from pathlib import Path

import polars as pl
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, render, style
from uniswap_lp_economics.viz import discovery as viz_discovery
from uniswap_lp_economics.viz import markouts as viz_markouts


def test_registered() -> None:
    stems = [s for s, _ in render.FIGURES]
    assert stems.index("02_stale_pool_episode") < stems.index("03_pool_follows_binance")
    assert stems.index("03_pool_follows_binance") < stems.index("04_markouts")


def test_markouts_has_one_panel_per_flow_label_searchers_first(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = viz_markouts.markouts(r)
        titles = [ax.get_title(loc="left") for ax in fig.axes]
    assert titles == ["Searchers", "Aggregators"]


def test_markouts_with_a_single_label_renders(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["markouts"] = frames["markouts"].filter(pl.col("flow_label") != "aggregator")
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("dark"):
        style.svg_bytes(viz_markouts.markouts(r))


def test_basis_panel_reports_the_share_inside_the_band(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = viz_discovery.pool_follows_binance(r)
        texts = " ".join(t.get_text() for t in fig.texts)
    h = r.basis_hist.with_columns(mid=(pl.col("bin_lo_bp") + pl.col("bin_hi_bp")) / 2)
    inside = h.filter(pl.col("mid").abs() < 5.0)["blocks"].sum() / h["blocks"].sum()
    assert f"{inside:.0%} of blocks" in texts
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_viz_discovery_markouts.py -q`
Expected: FAIL (modules missing).

- [ ] **Step 3: Write `viz/discovery.py`**

```python
"""Chapter 'Does the pool follow Binance?' (figure 3): basis distribution, how long gaps last,
and lead-lag, from sub-project 2's results."""

import numpy as np
import polars as pl
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter

from uniswap_lp_economics.discovery import EPISODE_THRESHOLDS_BP, FEE_BAND_BP
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import frame, new_figure, no_data, pal, pct

DURATION_TICKS_S = (12, 24, 60, 120, 300, 600, 1800)


def _duration(v: float) -> str:
    return f"{v / 60:.0f} min" if v >= 60 else f"{v:.0f} s"


def pool_follows_binance(r: Results) -> Figure:
    p = pal()
    fig, (a, b, c) = new_figure(1, 3, top=0.74, bottom=0.17, wspace=0.32)
    # (a) basis distribution
    h = r.basis_hist
    mid = ((h["bin_lo_bp"] + h["bin_hi_bp"]) / 2).to_numpy()
    width = (h["bin_hi_bp"] - h["bin_lo_bp"]).to_numpy()
    n = h["blocks"].to_numpy().astype(float)
    total = n.sum()
    inside = float(n[np.abs(mid) < FEE_BAND_BP].sum() / total) if total else float("nan")
    a.axvspan(-FEE_BAND_BP, FEE_BAND_BP, color=p.fees, alpha=0.12, lw=0)
    if total:
        a.bar(mid, n / total * 100, width=width, color=p.other, lw=0)
    else:
        no_data(a)
    a.set_xlim(-25, 25)
    a.set_title("(a) How far apart the venues are", loc="left", fontsize=10.5, color=p.ink)
    a.set_xlabel("Pool vs Binance at block start (bp)")
    a.set_ylabel("% of blocks")
    a.text(0.5, 0.95, f"{pct(inside)} of blocks inside\nthe ±{FEE_BAND_BP:g} bp fee band",
           transform=a.transAxes, ha="center", va="top", color=p.fees, fontsize=9.5)
    # (b) survival of gap episodes at the primary threshold
    k = EPISODE_THRESHOLDS_BP[0]
    d = np.sort(r.episodes.filter(pl.col("threshold_bp") == k)["duration_s"].drop_nulls()
                .to_numpy().astype(float))
    median = float(np.median(d)) if len(d) else float("nan")
    if len(d):
        share = 1.0 - np.arange(len(d)) / len(d)
        b.step(d, share, where="post", color=p.lvr, lw=2.2)
        b.set_xscale("log")
        ticks = [t for t in DURATION_TICKS_S if d[0] <= t <= d[-1]] or [float(d[0])]
        b.xaxis.set_major_locator(FixedLocator(ticks))
        b.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _duration(v)))
        b.xaxis.set_minor_formatter(NullFormatter())
        b.axvline(median, color=p.muted, lw=1, ls=(0, (3, 3)))
        b.text(median, 0.95, f" half close\n within {_duration(median)}", color=p.muted,
               fontsize=9, va="top")
    else:
        no_data(b)
    b.yaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v)))
    b.set_title("(b) How long gaps last", loc="left", fontsize=10.5, color=p.ink)
    b.set_xlabel(f"Gap outside ±{k:g} bp lasting at least")
    b.set_ylabel("Share of gaps")
    # (c) lead-lag
    xc = pl.DataFrame(r.summary["lead_lag"]["cross_correlation"])
    best_lag = 0
    if xc.height:
        lags = xc["lag_blocks"].to_list()
        corr = xc["corr"].to_list()
        c.bar(lags, corr, color=[p.fees if lag > 0 else p.other for lag in lags], width=0.7)
        best_lag = int(lags[int(np.argmax(corr))])
    else:
        no_data(c)
    c.axhline(0, color=p.muted, lw=0.8)
    c.set_title("(c) Who moves first", loc="left", fontsize=10.5, color=p.ink)
    c.set_xlabel("Lag in blocks (positive: Binance first)")
    c.set_ylabel("Correlation of per-block returns")
    lead = (f"pool returns track Binance's {best_lag} block{'s' if best_lag != 1 else ''} earlier"
            if best_lag > 0 else "the pool does not lag Binance in this sample")
    frame(
        fig,
        "The pool follows Binance: gaps open, and arbitrage closes them within blocks",
        f"{pct(inside)} of blocks start inside the fee band; half of the gaps outside "
        f"±{k:g} bp close within {_duration(median) if len(d) else 'n/a'}; {lead}.",
        "Basis = pool price / Binance last trade − 1 at block start, clipped to ±50 bp. "
        "Lead–lag: correlation of per-block log returns. Sub-project 2.",
    )
    return fig
```

- [ ] **Step 4: Write `viz/markouts.py`**

```python
"""Chapter 'Who wins against the pool?' (figure 4): markout small multiples by flow label."""

import numpy as np
import polars as pl
from matplotlib.figure import Figure

from uniswap_lp_economics.config import HORIZONS_S
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import fade_band, frame, new_figure, no_data, pal

HORIZON_LABELS = {0: "0 s", 12: "12 s", 60: "1 min", 300: "5 min", 3600: "1 h"}
FLOW_NAMES = {
    "searcher": "Searchers",
    "aggregator": "Aggregators",
    "uniswap_router": "Uniswap router",
    "intent_settlement": "Intent settlement",
    "other_contract": "Other contracts",
}


def _name(label: str) -> str:
    return FLOW_NAMES.get(label, label.replace("_", " ").capitalize())


def markouts(r: Results) -> Figure:
    p = pal()
    m = r.markouts
    by = m.filter(pl.col("grouping") == "flow_label")
    everyone = m.filter(pl.col("grouping") == "all").sort("horizon_s")
    labels = sorted({str(x) for x in by["flow_label"].to_list()},
                    key=lambda s: (s != "searcher", s))
    fig, axes = new_figure(1, max(len(labels), 1), sharey=True, top=0.74, bottom=0.17,
                           wspace=0.08)
    axes = np.atleast_1d(axes)
    if not labels:
        no_data(axes[0])
    x_all = [HORIZONS_S.index(h) for h in everyone["horizon_s"].to_list()]
    for ax, label in zip(axes, labels, strict=False):
        g = by.filter(pl.col("flow_label") == label).sort("horizon_s")
        x = [HORIZONS_S.index(h) for h in g["horizon_s"].to_list()]
        color = p.lvr if label == "searcher" else p.fees
        fade_band(ax, x, g["ci_lo_bp"].to_list(), g["ci_hi_bp"].to_list(), color)
        if everyone.height:
            ax.plot(x_all, everyone["mean_bp"].to_list(), color=p.faint, lw=1.2,
                    ls=(0, (4, 3)))
        mean = g["mean_bp"].to_list()
        ax.plot(x, mean, color=color, lw=2.2, marker="o", ms=4)
        ax.axhline(0, color=p.muted, lw=0.8)
        ax.text(x[0], mean[0], f"{mean[0]:+.1f} bp  ", ha="right", va="center", fontsize=9,
                color=color)
        ax.set_title(_name(label), loc="left", fontsize=11, fontweight="bold", color=color)
        ax.set_xticks(range(len(HORIZONS_S)),
                      [HORIZON_LABELS.get(h, f"{h} s") for h in HORIZONS_S], fontsize=8.5)
        ax.set_xlim(-0.8, len(HORIZONS_S) - 0.6)
    axes[0].set_ylabel("Trader markout vs Binance (bp of notional)")
    s0 = by.filter((pl.col("flow_label") == "searcher") & (pl.col("horizon_s") == 0))
    a0 = everyone.filter(pl.col("horizon_s") == 0)
    s_txt = f"searchers {float(s0['mean_bp'][0]):+.2f} bp" if s0.height else "no searcher flow"
    a_txt = f"all swaps {float(a0['mean_bp'][0]):+.2f} bp" if a0.height else ""
    frame(
        fig,
        "Searchers win against the pool; most other flow pays",
        f"Notional-weighted trader markout after the swap fee, 0 s to 1 h after the block. "
        f"At 0 s: {s_txt}; {a_txt}.",
        "Positive = the swap beat Binance's last trade at that horizon. Bands: 95% bootstrap "
        "over days (1,000 resamples). Dashed: all swaps. Sub-project 2.",
    )
    return fig
```

- [ ] **Step 5: Register**

In `viz/render.py` add `from uniswap_lp_economics.viz import discovery as viz_discovery` and
`from uniswap_lp_economics.viz import markouts as viz_markouts`; append to `FIGURES`:

```python
    ("03_pool_follows_binance", viz_discovery.pool_follows_binance),
    ("04_markouts", viz_markouts.markouts),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A src tests
git commit -m "viz: pool-follows-Binance and markout small multiples"
git push -q origin chart-redesign
```

---

### Task 7: Chapter "How big is LVR, and when?" — figures 5, 6, 7

**Files:**
- Create: `src/uniswap_lp_economics/viz/fees_vs_lvr.py`
- Modify: `src/uniswap_lp_economics/viz/render.py`
- Test: `tests/test_viz_fees_vs_lvr.py`

**Interfaces:**
- Consumes: `r.daily` (columns of `lvr_daily.csv`), `r.summary["lp"]["daily"]`.
- Produces: `lvr_vs_volatility(r) -> Figure`, `cumulative(r) -> Figure`,
  `measured_vs_theory(r) -> Figure`, `fit_loglog(x, y) -> tuple[float, float]` (slope, intercept),
  `break_even(fit_a, fit_b) -> float`.

- [ ] **Step 1: Write the failing tests**

`tests/test_viz_fees_vs_lvr.py`:

```python
import math
from pathlib import Path

import polars as pl
import pytest
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, fees_vs_lvr, render, style


def test_registered_in_order() -> None:
    stems = [s for s, _ in render.FIGURES]
    i = stems.index("05_lvr_vs_volatility")
    assert stems[i : i + 3] == [
        "05_lvr_vs_volatility", "06_cumulative_fees_vs_lvr", "07_measured_vs_theory"
    ]


def test_loglog_fit_and_break_even() -> None:
    x = [0.1, 0.2, 0.4]
    lvr = fees_vs_lvr.fit_loglog(x, [v**2 * 100 for v in x])
    fees = fees_vs_lvr.fit_loglog(x, [v * 25 for v in x])
    assert lvr[0] == pytest.approx(2.0) and fees[0] == pytest.approx(1.0)
    assert fees_vs_lvr.break_even(lvr, fees) == pytest.approx(0.25)  # 100 s^2 = 25 s


def test_zero_and_negative_days_are_left_off_the_log_axes(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["daily"] = frames["daily"].with_columns(
        lvr_0=pl.Series([0.0, -3.0, 22.0, 30.0, 50.0, 95.0])
    )
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        style.svg_bytes(fees_vs_lvr.lvr_vs_volatility(r))


def test_cumulative_subtitle_quotes_the_bootstrap_interval(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = fees_vs_lvr.cumulative(r)
        texts = " ".join(t.get_text() for t in fig.texts)
    assert "−$80" in texts and "−$110 to −$50" in texts


def test_measured_vs_theory_ratios(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    d = r.daily
    ratio = d["lvr_0_searcher"].sum() / d["theory_1s"].sum()
    with style.theme("light"):
        fig = fees_vs_lvr.measured_vs_theory(r)
        texts = " ".join(t.get_text() for t in fig.texts)
    assert f"{ratio:.2f}×" in texts and not math.isnan(ratio)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_viz_fees_vs_lvr.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `viz/fees_vs_lvr.py`**

```python
"""Chapter 'How big is LVR, and when?': LVR and fees against volatility (figure 5), cumulative
fees vs LVR (figure 6) and measured vs theoretical LVR (figure 7)."""

from collections.abc import Sequence

import numpy as np
import polars as pl
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import USD_FMT, frame, new_figure, no_data, pal, pct, usd

SOURCE_MEASURED = (
    "Uniswap V3 USDC/WETH 0.05%, Jul–Sep 2026. LVR measured per swap against Binance's last "
    "trade at block time."
)


def fit_loglog(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    """OLS of log y on log x: (slope, intercept)."""
    slope, intercept = np.polyfit(np.log(np.asarray(x, float)), np.log(np.asarray(y, float)), 1)
    return float(slope), float(intercept)


def break_even(a: tuple[float, float], b: tuple[float, float]) -> float:
    """x where the two log-log fits cross."""
    return float(np.exp((b[1] - a[1]) / (a[0] - b[0])))


def lvr_vs_volatility(r: Results) -> Figure:
    p = pal()
    d = r.daily.with_columns(total_fees=pl.col("fees_usd") + pl.col("protocol_fee_usd"))
    fig, ax = new_figure(right=0.84)
    pos = d.filter((pl.col("sigma_annual") > 0) & (pl.col("lvr_0") > 0) & (pl.col("total_fees") > 0))
    if pos.height < 2:
        no_data(ax, "too few days with positive LVR and fees")
        frame(fig, "Arbitrage losses against volatility", "Not enough data.", SOURCE_MEASURED)
        return fig
    sig = pos["sigma_annual"].to_numpy()
    lvr_fit = fit_loglog(sig, pos["lvr_0"].to_list())
    fee_fit = fit_loglog(sig, pos["total_fees"].to_list())
    th = d.filter((pl.col("sigma_annual") > 0) & (pl.col("theory_1s") > 0))
    ax.scatter(th["sigma_annual"], th["theory_1s"], s=10, color=p.faint, alpha=0.7, lw=0,
               zorder=2)
    xs = np.linspace(sig.min() * 0.95, sig.max() * 1.05, 200)
    for y, (b, a), c, name, dy in (
        (pos["lvr_0"], lvr_fit, p.lvr, "LVR", 16),
        (pos["total_fees"], fee_fit, p.fees, "Swap fees", -16),
    ):
        ax.scatter(sig, y, s=34, color=c, alpha=0.55, edgecolor=p.background, lw=0.6, zorder=3)
        fit = np.exp(a) * xs**b
        ax.plot(xs, fit, color=c, lw=2.2, zorder=4)
        ax.annotate(name + "\n" + r"$\propto \sigma^{" + f"{b:.2f}" + "}$", (xs[-1], fit[-1]),
                    xytext=(6, dy), textcoords="offset points", color=c, fontsize=11,
                    fontweight="bold", va="center", ha="left", annotation_clip=False)
    ax.text(xs[-1], th["theory_1s"].min() if th.height else 1.0, "grey: LVR formula\n(1 s returns)",
            color=p.faint, fontsize=9, ha="left", va="bottom")
    s_star = break_even(lvr_fit, fee_fit)
    crosses = sig.min() <= s_star <= sig.max()
    if crosses:
        ax.axvline(s_star, color=p.muted, lw=1, ls=(0, (3, 3)), zorder=1)
        ymax = ax.get_ylim()[1]
        ax.text(s_star * 0.96, ymax, "← fees exceed LVR", ha="right", va="top", color=p.fees,
                fontsize=10, fontstyle="italic")
        ax.text(s_star * 1.04, ymax, "LVR exceeds fees →", ha="left", va="top", color=p.lvr,
                fontsize=10, fontstyle="italic")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v)))
    ax.xaxis.set_minor_formatter(FuncFormatter(lambda v, _: pct(v) if round(v, 2) in (0.3, 0.5, 0.7) else ""))
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.grid(True, axis="both", which="major")
    ax.set_xlabel("Daily realised volatility of ETH on Binance (annualised, log scale)")
    ax.set_ylabel("USD per day (log scale)")
    tail = (f" Above about {pct(s_star)} volatility the pool pays more to arbitrage than it earns "
            "in fees." if crosses else "")
    frame(
        fig,
        "Arbitrage losses grow faster with volatility than fees do",
        f"Each dot is one day. Swap fees (LP + protocol) grow as σ^{fee_fit[0]:.2f}, LVR as "
        f"σ^{lvr_fit[0]:.2f}.\n{tail.strip()}",
        f"{SOURCE_MEASURED} Log-log OLS fits.\nThe formula at fixed liquidity predicts σ²; "
        "a flatter measured slope fits LPs pulling liquidity on volatile days.",
    )
    return fig


def cumulative(r: Results) -> Figure:
    p = pal()
    d = r.daily.sort("day")
    s = r.summary["lp"]["daily"]
    fig, ax = new_figure(right=0.80)
    x = d["day"].to_list()
    lp = np.cumsum(d["fees_usd"].to_numpy())
    total = np.cumsum((d["fees_usd"] + d["protocol_fee_usd"]).to_numpy())
    lvr = np.cumsum(d["lvr_0"].to_numpy())
    ax.fill_between(x, lp, lvr, where=lvr >= lp, color=p.lvr, alpha=0.14, lw=0)
    ax.plot(x, lvr, color=p.lvr, lw=2.4)
    ax.plot(x, lp, color=p.fees, lw=2.4)
    ax.plot(x, total, color=p.fees, lw=1.3, ls=(0, (4, 3)))
    for y, text, c in ((lvr[-1], f"LVR  {usd(lvr[-1])}", p.lvr), (lp[-1], f"LP fees  {usd(lp[-1])}", p.fees),
                       (total[-1], f"LP + protocol fees  {usd(total[-1])}", p.fees)):
        ax.annotate(text, (x[-1], y), xytext=(8, 0), textcoords="offset points", va="center",
                    color=c, fontsize=9.5, fontweight="bold", annotation_clip=False)
    worst = int(np.argmax(d["lvr_0"].to_numpy()))
    ax.annotate(f"{x[worst]:%d %b}: {usd(float(d['lvr_0'][worst]))} of LVR in one day",
                (x[worst], lvr[worst]), xytext=(-12, 26), textcoords="offset points", ha="right",
                fontsize=9, color=p.muted, arrowprops={"arrowstyle": "-", "color": p.muted, "lw": 0.8})
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.xaxis.set_major_formatter(DateFormatter("%d %b"))
    ax.set_ylabel("Cumulative USD since the window start")
    frame(
        fig,
        "Over the quarter, LVR pulled steadily ahead of LP fees",
        f"LP fees − LVR: {usd(s['fees_minus_lvr_usd'])} (95% interval "
        f"{usd(s['fees_minus_lvr_ci_lo_usd'])} to {usd(s['fees_minus_lvr_ci_hi_usd'])}). Before the "
        f"protocol's cut, total fees fell short by only {usd(-s['total_fees_minus_lvr_usd'])}\n"
        f"(interval {usd(s['total_fees_minus_lvr_ci_lo_usd'])} to "
        f"{usd(s['total_fees_minus_lvr_ci_hi_usd'])}), and LVR beat LP fees on "
        f"{s['days_lvr_above_lp_fees']} of {s['days']} days.",
        f"{SOURCE_MEASURED} Intervals: bootstrap over days (1,000 resamples, seed 42).",
    )
    return fig


def measured_vs_theory(r: Results) -> Figure:
    p = pal()
    d = r.daily.with_columns(
        gross=pl.col("lvr_0_searcher") - pl.col("fees_searcher") - pl.col("protocol_fees_searcher")
    )
    fig, (a, b) = new_figure(1, 2, top=0.76, bottom=0.15, wspace=0.25)
    ratios = []
    for ax, xcol, ycol, title, c in (
        (a, "theory_1s", "lvr_0_searcher", "(a) Before fees: LVR on searcher swaps", p.lvr),
        (b, "theory_arb", "gross", "(b) After fees: searchers' gross vs theory × P_trade", p.jit),
    ):
        xv, yv = d[xcol].to_numpy() / 1e3, d[ycol].to_numpy() / 1e3
        hi = max(float(np.nanmax(xv)), float(np.nanmax(yv)), 1e-9) * 1.05
        lo = min(0.0, float(np.nanmin(yv)))
        ax.plot([lo, hi], [lo, hi], color=p.muted, lw=1, ls=(0, (3, 3)))
        ax.scatter(xv, yv, s=30, color=c, alpha=0.6, edgecolor=p.background, lw=0.5)
        ratio = float(d[ycol].sum() / d[xcol].sum()) if d[xcol].sum() else float("nan")
        ratios.append(ratio)
        ax.text(0.04, 0.95, f"measured / theory = {ratio:.2f}×\nover the window",
                transform=ax.transAxes, va="top", fontsize=9.5, color=c)
        ax.text(hi, hi, " 45°", color=p.muted, fontsize=8.5, va="bottom")
        ax.set_title(title, loc="left", fontsize=10.5, color=p.ink)
        ax.set_xlabel("Theory, USD thousands per day")
        ax.set_ylabel("Measured, USD thousands per day")
        ax.grid(True, axis="both")
    frame(
        fig,
        "Measured arbitrage runs above the LVR formula, before and after fees",
        f"Each dot is one day. Before fees, measured LVR on searcher swaps is {ratios[0]:.2f}× "
        f"the formula; after LP and protocol fees, searchers' gross is {ratios[1]:.2f}× the "
        "formula's expected arbitrage profit.",
        "Theory: Milionis et al. (2022) with 1 s Binance returns; P_trade from Milionis, "
        "Moallemi, Roughgarden (2023), 0.05% fee and 12 s blocks.",
    )
    return fig
```

- [ ] **Step 4: Register**

In `viz/render.py` add `from uniswap_lp_economics.viz import fees_vs_lvr` and append:

```python
    ("05_lvr_vs_volatility", fees_vs_lvr.lvr_vs_volatility),
    ("06_cumulative_fees_vs_lvr", fees_vs_lvr.cumulative),
    ("07_measured_vs_theory", fees_vs_lvr.measured_vs_theory),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "viz: LVR vs volatility, cumulative fees vs LVR, measured vs theory"
git push -q origin chart-redesign
```

---

### Task 8: Chapter "Do arbitrage bots keep the edge?" — figure 8

**Files:**
- Create: `src/uniswap_lp_economics/viz/bots.py`
- Modify: `src/uniswap_lp_economics/viz/render.py`
- Test: `tests/test_viz_bots.py`

**Interfaces:**
- Consumes: `r.summary["arbitrage"]`, `r.bot_profit` (`sender`, `gross_usd`, `kept_usd`).
- Produces: `bots_keep(r) -> Figure`, `WATERFALL: tuple[tuple[str, str, str], ...]`.

- [ ] **Step 1: Write the failing test**

`tests/test_viz_bots.py`:

```python
from pathlib import Path

from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import bots, data, render, style


def test_registered_after_figure_7() -> None:
    stems = [s for s, _ in render.FIGURES]
    assert stems.index("07_measured_vs_theory") + 1 == stems.index("08_bots_keep")


def test_bots_subtitle_and_bot_rows(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = bots.bots_keep(r)
        texts = " ".join(t.get_text() for t in fig.texts)
        right = fig.axes[1]
        labels = [t.get_text() for t in right.get_yticklabels()]
    assert "$60" in texts and "−$6" in texts
    assert "TOTAL" not in " ".join(labels) and len(labels) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_viz_bots.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `viz/bots.py`**

```python
"""Chapter 'Do arbitrage bots keep the edge?' (figure 8): available -> kept waterfall and each
top bot's gross vs kept (sub-project 2)."""

import polars as pl
from matplotlib.figure import Figure

from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import USD_FMT, frame, new_figure, no_data, pal, usd

# (summary.arbitrage key, label, kind): "total" bars stand on zero, "minus" bars float down
WATERFALL = (
    ("available_usd", "Available\nat block starts", "total"),
    ("captured_searchers_usd", "Captured\nby searchers", "total"),
    ("top_bot_single_pool_gross_usd", "Top bots'\nsingle-pool gross", "total"),
    ("gas_burned_usd", "Base fee\nburned", "minus"),
    ("priority_fee_usd", "Priority\nfee", "minus"),
    ("coinbase_usd", "Direct\npayment", "minus"),
    ("kept_usd", "Kept\n(upper bound)", "total"),
)


def bots_keep(r: Results) -> Figure:
    p = pal()
    w = r.summary["arbitrage"]
    fig, (a, b) = new_figure(1, 2, top=0.76, bottom=0.20, wspace=0.42, width_ratios=[1.6, 1.0])
    level = 0.0
    for i, (key, label, kind) in enumerate(WATERFALL):
        v = float(w.get(key) or 0.0)
        if kind == "total":
            color = p.lvr if key == "kept_usd" and v < 0 else p.fees if key == "kept_usd" else p.other
            a.bar(i, v, color=color, width=0.62)
            level = v
            a.text(i, max(v, 0), usd(v), ha="center", va="bottom", fontsize=9, color=p.ink)
        else:
            a.bar(i, -v, bottom=level, color=p.builder if key != "gas_burned_usd" else p.faint,
                  width=0.62)
            a.text(i, level, f"−{usd(v)}", ha="center", va="bottom", fontsize=9, color=p.muted)
            level -= v
    a.axhline(0, color=p.muted, lw=0.8)
    a.set_xticks(range(len(WATERFALL)), [label for _, label, _ in WATERFALL], fontsize=8.5)
    a.yaxis.set_major_formatter(USD_FMT)
    a.set_title("(a) From available arbitrage to what bots kept", loc="left", fontsize=10.5,
                color=p.ink)
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
        b.text(0.98, 0.02, "bar: gross at 0 s\ndot: kept", transform=b.transAxes, ha="right",
               va="bottom", fontsize=9, color=p.muted)
    else:
        no_data(b)
    b.set_title("(b) Per top bot", loc="left", fontsize=10.5, color=p.ink)
    g, k = float(w.get("top_bot_single_pool_gross_usd") or 0), float(w.get("kept_usd") or 0)
    frame(
        fig,
        "Arbitrage bots hand most of their edge to block builders",
        f"Top bots' single-pool gross at 0 s: {usd(g)}. After the base fee, priority fees and "
        f"direct payments to the block's fee recipient, they kept {usd(k)} (an upper bound).",
        "Sub-project 2. Available = arbitrage available at block starts before gas and Binance "
        "fees. Kept misses payments outside the transaction.",
    )
    return fig
```

- [ ] **Step 4: Register**

In `viz/render.py` add `from uniswap_lp_economics.viz import bots` and append
`("08_bots_keep", bots.bots_keep),`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "viz: bots keep-the-edge waterfall"
git push -q origin chart-redesign
```

---

### Task 9: Chapter "Who pays?" — figures 9, 10, 12

**Files:**
- Create: `src/uniswap_lp_economics/viz/who_pays.py`
- Modify: `src/uniswap_lp_economics/viz/render.py`
- Test: `tests/test_viz_who_pays.py`

**Interfaces:**
- Consumes: `r.positions` (`position_id, lp_type, twv_usd, pnl_rebal_usd`), `r.groups`
  (`lp_groups.csv`), `r.summary["lp"]["lifetime"|"lifetime_by_life"|"lifetime_by_width"]`;
  `pnl.WIDTH_BUCKETS`, `style.per_10k_month`.
- Produces: `every_position(r)`, `pnl_by_group(r)`, `lifetime(r)` (each `-> Figure`),
  `LP_NAMES`, `LIFE_NAMES`, `WIDTH_NAMES: dict[str, str]`, `MIN_VALUE_USD = 100.0`.

- [ ] **Step 1: Write the failing tests**

`tests/test_viz_who_pays.py`:

```python
from pathlib import Path

import polars as pl
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, render, style, who_pays


def test_registered() -> None:
    stems = [s for s, _ in render.FIGURES]
    for stem in ("09_every_position", "10_pnl_by_group", "12_lifetime"):
        assert stem in stems
    assert stems.index("08_bots_keep") < stems.index("09_every_position") < stems.index("10_pnl_by_group")


def test_every_position_counts_hidden_dust(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = who_pays.every_position(r)
        texts = " ".join(t.get_text() for t in fig.texts)
    assert "1 position worth under $100" in texts  # the $0.50 dust position


def test_figures_render_without_jit_or_vaults(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["positions"] = frames["positions"].filter(~pl.col("lp_type").is_in(["jit", "lp_vault"]))
    frames["groups"] = frames["groups"].filter(~pl.col("group").is_in(["jit", "lp_vault"]))
    r = data.load_results(write_results(tmp_path, frames))
    for fn in (who_pays.every_position, who_pays.pnl_by_group, who_pays.lifetime):
        with style.theme("dark"):
            style.svg_bytes(fn(r))


def test_pnl_by_group_uses_the_10k_month_framing(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = who_pays.pnl_by_group(r)
        texts = " ".join(t.get_text() for t in fig.texts)
    assert "−$39" in texts  # wallet NFTs: −1.3 bp/day × 30


def test_zero_value_positions_are_dropped_from_the_log_axis(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["positions"] = frames["positions"].with_columns(
        pl.when(pl.col("position_id") == "w1").then(0.0).otherwise(pl.col("twv_usd")).alias("twv_usd")
    )
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        style.svg_bytes(who_pays.every_position(r))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_viz_who_pays.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `viz/who_pays.py`**

```python
"""Chapter 'Who pays?': every position (figure 9), P&L by group in USD per $10,000 per month
(figure 10) and lifetime vs holding (figure 12)."""

from typing import Any

import polars as pl
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from uniswap_lp_economics.lp.pnl import WIDTH_BUCKETS
from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import (
    USD_FMT,
    frame,
    new_figure,
    no_data,
    pal,
    pct,
    per_10k_month,
    usd,
)

MIN_VALUE_USD = 100.0
LP_NAMES = {
    "jit": "JIT (same block)",
    "nft_wallet": "Wallet NFT",
    "lp_vault": "Vault",
    "nft_contract": "Contract NFT",
    "direct_other": "Other direct",
}
LIFE_NAMES = {"<1d": "Under a day", "1-7d": "1–7 days", "7-30d": "7–30 days",
              "30-180d": "30–180 days", ">=180d": "180 days or more"}
WIDTH_NAMES = {"<50": "Under 50 bp", "50-200": "50–200 bp", "200-1000": "200–1,000 bp",
               "1000-5000": "1,000–5,000 bp", ">=5000": "5,000 bp or more"}
PNL_SOURCE = ("P&L = fees − LVR (0 s) − gas − direct builder payments, against a portfolio that "
              "rebalances at Binance's last trade.")


def every_position(r: Results) -> Figure:
    p = pal()
    pos_all = r.positions
    pos = pos_all.filter(pl.col("twv_usd") >= MIN_VALUE_USD)
    hidden = pos_all.height - pos.height
    fig, ax = new_figure(left=0.10, right=0.79)
    colors = {"jit": p.jit, "nft_wallet": p.fees}
    for t in ("nft_contract", "direct_other", "lp_vault", "nft_wallet", "jit"):
        g = pos.filter(pl.col("lp_type") == t)
        if g.height:
            ax.scatter(g["twv_usd"], g["pnl_rebal_usd"], s=13 if t == "jit" else 9,
                       color=colors.get(t, p.other), alpha=0.65 if t == "jit" else 0.35, lw=0,
                       zorder=3 if t == "jit" else 2)
    if pos.height == 0:
        no_data(ax, f"no position worth ${MIN_VALUE_USD:.0f} or more")
    else:
        ax.set_xscale("log")
        ax.set_yscale("symlog", linthresh=10)
        ax.set_xlim(MIN_VALUE_USD, float(pos["twv_usd"].max()) * 1.6)
    ax.axhline(0, color=p.ink, lw=0.9, zorder=1)
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.xaxis.set_major_formatter(USD_FMT)
    ax.grid(True, axis="both")
    slots = (("jit", 0.86, p.jit), ("nft_wallet", 0.60, p.fees), ("lp_vault", 0.34, p.muted))
    for t, y, c in slots:
        g = pos_all.filter(pl.col("lp_type") == t)
        if g.height:
            share = float((g["pnl_rebal_usd"] > 0).mean())  # type: ignore[arg-type]
            ax.text(1.015, y, f"{LP_NAMES[t]}\n{g.height:,} positions\n"
                    f"{usd(float(g['pnl_rebal_usd'].sum()))} in total\n{pct(share)} made money",
                    transform=ax.transAxes, fontsize=9.5, color=c, va="center", fontweight="bold")
    ax.text(1.015, 0.12, "Grey: vaults, contract\nNFTs, other direct", transform=ax.transAxes,
            fontsize=9, color=p.muted, va="center")
    ax.set_xlabel("Average position value while open (log scale)")
    ax.set_ylabel("P&L vs rebalancing at Binance (symlog)")
    lose = float((pos_all["pnl_rebal_usd"] < 0).mean()) if pos_all.height else 0.0  # type: ignore[arg-type]
    plural = "position" if hidden == 1 else "positions"
    frame(
        fig,
        "Almost every LP lost to arbitrage; JIT is a coin flip",
        f"Each dot is one of the {pos_all.height:,} positions active in the window. {pct(lose)} "
        "lost money after fees, gas and builder payments;\nthe losses scale with size. JIT "
        "positions are large but live for a single block.",
        f"{PNL_SOURCE} Symlog axis: linear within ±$10.\n{hidden:,} {plural} worth under "
        f"${MIN_VALUE_USD:.0f} not drawn; the group totals on the right include them.",
    )
    return fig


def _dots(ax: Axes, rows: list[dict[str, Any]], names: dict[str, str], color: str) -> None:
    p = pal()
    for i, row in enumerate(rows):
        v = per_10k_month(row["bp_per_day"])
        lo, hi = per_10k_month(row["ci_lo_bp"]), per_10k_month(row["ci_hi_bp"])
        ax.plot([i, i], [lo, hi], color=color, lw=7, alpha=0.16, solid_capstyle="round")
        ax.plot([i, i], [lo, hi], color=color, lw=1.6, alpha=0.6)
        spans = lo <= 0 <= hi
        ax.scatter([i], [v], s=70, zorder=3, facecolor=p.background if spans else color,
                   edgecolor=color, lw=2)
        ax.text(i + 0.12, v, usd(v), va="center", fontsize=9, color=p.ink)
    ax.axhline(0, color=p.muted, lw=0.8)
    ax.set_xticks(range(len(rows)), [names.get(row["group"], row["group"]) for row in rows],
                  fontsize=8.5, rotation=20, ha="right")
    ax.set_xlim(-0.6, max(len(rows), 1) - 0.4)
    ax.yaxis.set_major_formatter(USD_FMT)


def pnl_by_group(r: Results) -> Figure:
    p = pal()
    g = r.groups
    types = [row for t in ("nft_wallet", "lp_vault", "nft_contract", "direct_other")
             for row in g.filter((pl.col("grouping") == "lp_type") & (pl.col("group") == t)).to_dicts()]
    jit = g.filter((pl.col("grouping") == "lp_type") & (pl.col("group") == "jit")).to_dicts()
    widths = [row for w in WIDTH_BUCKETS
              for row in g.filter((pl.col("grouping") == "width_bucket") & (pl.col("group") == w)).to_dicts()]
    fig, (a, j, w) = new_figure(1, 3, top=0.74, bottom=0.22, wspace=0.35,
                                width_ratios=[4, 1.3, 5])
    for ax, rows, names, color, title in (
        (a, types, LP_NAMES, p.fees, "(a) By LP type"),
        (j, jit, LP_NAMES, p.jit, "(b) JIT, own scale"),
        (w, widths, WIDTH_NAMES, p.other, "(c) By range width"),
    ):
        if rows:
            _dots(ax, rows, names, color)
        else:
            no_data(ax, "none")
        ax.set_title(title, loc="left", fontsize=10.5, color=p.ink)
    a.set_ylabel("USD per $10,000 of position value per month")
    wallet = next((row for row in types if row["group"] == "nft_wallet"), None)
    lead = (f"Wallet NFTs, which earned most of the fees: {usd(per_10k_month(wallet['bp_per_day']))} "
            f"per month ({usd(per_10k_month(wallet['ci_lo_bp']))} to "
            f"{usd(per_10k_month(wallet['ci_hi_bp']))})." if wallet else "")
    frame(
        fig,
        "Every LP type except JIT lost money, and JIT's result could be luck",
        "P&L against rebalancing at Binance, in USD per $10,000 of time-weighted position value "
        f"per 30 days. {lead}",
        f"{PNL_SOURCE} 95% intervals: bootstrap over positions. Hollow dot: the interval spans "
        "zero.",
    )
    return fig


def lifetime(r: Results) -> Figure:
    p = pal()
    lp = r.summary["lp"]
    fig, axes = new_figure(1, 2, left=0.13, top=0.76, bottom=0.14, wspace=0.55)
    for ax, rows, key, names, title in (
        (axes[0], lp["lifetime_by_life"], "life_bucket", LIFE_NAMES, "(a) By how long it lived"),
        (axes[1], lp["lifetime_by_width"], "width_bucket", WIDTH_NAMES, "(b) By range width"),
    ):
        if not rows:
            no_data(ax)
            continue
        ys = list(range(len(rows)))
        vals = [float(row["share_beat_hold"]) for row in rows]
        ax.axvline(0.5, color=p.muted, lw=1, ls=(0, (3, 3)))
        ax.hlines(ys, 0.5, vals, color=p.faint, lw=2)
        ax.scatter(vals, ys, s=80, zorder=3, color=[p.fees if v >= 0.5 else p.lvr for v in vals])
        for y, v, row in zip(ys, vals, rows, strict=True):
            ax.text(v + (0.03 if v >= 0.5 else -0.03), y, f"{pct(v)}  ({row['positions']:,})",
                    va="center", ha="left" if v >= 0.5 else "right", fontsize=9, color=p.ink)
        ax.set_yticks(ys, [names.get(row[key], row[key]) for row in rows])
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v)))
        ax.grid(True, axis="x")
        ax.grid(False, axis="y")
        ax.set_title(title, loc="left", fontsize=10.5, color=p.ink)
    o = lp["lifetime"]
    old = next((row for row in lp["lifetime_by_life"] if row["life_bucket"] == ">=180d"), None)
    tail = f"; {pct(old['share_beat_hold'])} of those that lived 180 days or more" if old else ""
    frame(
        fig,
        "Over their whole life, about half of LPs beat simply holding",
        f"Share of window-active positions whose lifetime result beat holding the deposited "
        f"tokens: {pct(o['share_beat_hold'])} overall{tail}. Numbers in brackets: positions.",
        "Gas and builder payments inside the window are charged; costs before it are not "
        "observed. Shares count positions, not dollars, and depend on each position's price path.",
    )
    return fig
```

- [ ] **Step 4: Register**

In `viz/render.py` add `from uniswap_lp_economics.viz import who_pays` and append:

```python
    ("09_every_position", who_pays.every_position),
    ("10_pnl_by_group", who_pays.pnl_by_group),
```

and, after the line Task 10 will add for figure 11 (add it now at the end; Task 10 inserts its
entry before it): `("12_lifetime", who_pays.lifetime),`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "viz: every position, P&L per \$10k per month, lifetime vs holding"
git push -q origin chart-redesign
```

---

### Task 10: Anatomy of one JIT block — figure 11

**Files:**
- Create: `src/uniswap_lp_economics/viz/jit_block.py`
- Modify: `src/uniswap_lp_economics/viz/render.py`
- Test: `tests/test_viz_jit_block.py`

**Interfaces:**
- Consumes: `r.jit_block` (`figdata.JIT_BLOCK_SCHEMA` columns), `r.positions` (`position_id,
  fee_usd, lvr_0, gas_usd, direct_usd, pnl_rebal_usd`), `style.*`.
- Produces: `jit_block(r) -> Figure`, `MAX_CONTEXT = 1`.

- [ ] **Step 1: Write the failing tests**

`tests/test_viz_jit_block.py`:

```python
from pathlib import Path

import polars as pl
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, jit_block, render, style


def test_registered_between_10_and_12() -> None:
    stems = [s for s, _ in render.FIGURES]
    assert stems.index("10_pnl_by_group") + 1 == stems.index("11_jit_block")
    assert stems.index("11_jit_block") + 1 == stems.index("12_lifetime")


def test_jit_block_labels_events_and_totals(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = jit_block.jit_block(r)
        texts = " ".join(t.get_text() for t in fig.texts + fig.axes[0].texts)
    assert "Block 12" in texts and "Operator's swap" in texts and "JIT adds" in texts
    assert "P&L vs rebalancing" in texts and "$11" in texts


def test_empty_jit_block_says_so(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["jit_block"] = frames["jit_block"].head(0)
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("dark"):
        fig = jit_block.jit_block(r)
        texts = " ".join(t.get_text() for t in fig.texts + fig.axes[0].texts)
        style.svg_bytes(fig)
    assert "no JIT position" in texts


def test_fallback_title_without_the_full_pattern(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["jit_block"] = frames["jit_block"].with_columns(full_pattern=pl.lit(False))
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        fig = jit_block.jit_block(r)
        title = fig.texts[0].get_text()
    assert title.startswith("Inside the most profitable JIT block")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_viz_jit_block.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `viz/jit_block.py`**

```python
"""Figure 11: one real JIT block, event by event, with the position's totals."""

from typing import Any

import numpy as np
import polars as pl
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from uniswap_lp_economics.viz.data import Results
from uniswap_lp_economics.viz.style import frame, new_figure, no_data, pal, usd

MAX_CONTEXT = 1  # other events shown before the first and after the last JIT/operator event
SOURCE = ("Operator = the JIT position's own transactions. Markout = the swap's result against "
          "Binance at 0 s. Position totals from positions.csv.")


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
    return row["event"].capitalize()


def jit_block(r: Results) -> Figure:
    p = pal()
    t = r.jit_block.sort("log_index")
    fig, ax = new_figure(right=0.75, top=0.76, bottom=0.30)
    if t.height == 0:
        no_data(ax, "no JIT position in the window")
        frame(fig, "Inside a JIT block", "No JIT position in the window.", SOURCE)
        return fig
    roles = t["role"].to_list()
    keyed = [i for i, role in enumerate(roles) if role != "other"]
    lo, hi = max(keyed[0] - MAX_CONTEXT, 0), min(keyed[-1] + MAX_CONTEXT, t.height - 1)
    t = t.slice(lo, hi - lo + 1)
    rows = t.to_dicts()
    x = np.arange(len(rows))
    price = t["pool_price_after"].to_numpy().astype(float)
    ax.step(np.append(x, x[-1] + 1) - 0.5, np.append(price, price[-1]), where="post",
            color=p.fees, lw=2.2)
    colors = {"operator": p.lvr, "jit": p.jit, "other": p.other}
    for i, row in enumerate(rows):
        ax.scatter([i], [price[i]], s=90, color=colors[row["role"]], zorder=4,
                   edgecolor=p.background, lw=1)
        ax.annotate(_caption(row), (i, 0), xycoords=("data", "axes fraction"), xytext=(0, -10),
                    textcoords="offset points", ha="center", va="top", fontsize=8.5,
                    color=colors[row["role"]])
    ax.set_xticks([])
    ax.set_xlim(-0.6, len(rows) - 0.4)
    pad = max(float(price.max() - price.min()) * 0.3, 1.0)
    ax.set_ylim(price.min() - pad, price.max() + pad)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.set_ylabel("Pool price after the event")
    pid, block = rows[0]["position_id"], int(rows[0]["block_number"])
    if bool(rows[0]["full_pattern"]):
        title = "Inside one JIT block: the operator's own swaps bracket its liquidity"
        sub = (f"Block {block:,}, pool events in order. The JIT operator swaps before adding "
               "liquidity and after removing it; the swap in between is the one the JIT "
               "position serves.")
    else:
        title = "Inside the most profitable JIT block"
        sub = (f"Block {block:,}, pool events in order. No JIT position in the window had its "
               "own swaps on both sides of its liquidity; this is the most profitable one.")
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
        ]
        y = 0.70
        fig.text(0.78, y + 0.06, "This JIT position", fontsize=10.5, fontweight="bold", color=p.ink)
        for label, v, c in lines:
            fig.text(0.78, y, label, fontsize=9.5, color=p.muted)
            fig.text(0.985, y, usd(float(v)) if v is not None else "n/a", fontsize=9.5, color=c,
                     ha="right", fontweight="bold")
            y -= 0.05
    return fig
```

- [ ] **Step 4: Register**

In `viz/render.py` add `from uniswap_lp_economics.viz import jit_block as viz_jit_block` and insert
`("11_jit_block", viz_jit_block.jit_block),` between `"10_pnl_by_group"` and `"12_lifetime"`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "viz: anatomy of one JIT block"
git push -q origin chart-redesign
```

---

### Task 11: Hero Sankey and the social card

**Files:**
- Create: `src/uniswap_lp_economics/viz/hero.py`
- Modify: `src/uniswap_lp_economics/viz/render.py`
- Test: `tests/test_viz_hero.py`

**Interfaces:**
- Consumes: `r.summary["lp"]["destination"]`, `r.summary["lp"]["fees_minus_lvr_usd"]`.
- Produces: `flows(dest: dict[str, Any], p: Palette) -> tuple[list[Node], list[Node]]` (sources,
  destinations; `Node = tuple[str, float, str]` = label, USD, colour), `pieces(sources, dests) ->
  list[tuple[int, int, float]]`, `hero(r, size=CANVAS) -> Figure`, `social_card(r, out_dir) -> list[Path]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_viz_hero.py`:

```python
from pathlib import Path

import pytest
from PIL import Image
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, hero, render, style


def test_hero_first_and_card_registered() -> None:
    assert render.FIGURES[0][0] == "00_hero"
    assert hero.social_card in render.EXTRAS


def test_negative_kept_becomes_a_source_and_flows_balance() -> None:
    d = fixture_frames()["summary"]["lp"]["destination"]
    src, dst = hero.flows(d, style.PALETTES["light"])
    assert [s[0] for s in src][1].startswith("Paid by searchers")
    assert sum(s[1] for s in src) == pytest.approx(sum(t[1] for t in dst))
    split = hero.pieces(src, dst)
    assert sum(a for _, _, a in split) == pytest.approx(106.0)
    assert split[-1][0] == 1  # the searchers' own money flows to the last destinations


def test_positive_kept_and_negative_flow_still_balance() -> None:
    d = dict(fixture_frames()["summary"]["lp"]["destination"])
    # sources 100 + 4 (negative multi-pool) = destinations 48 + 16 + 1 + 16 + 19 + 4 (kept)
    d.update(searcher_kept_usd=4.0, multi_pool_gross_usd=-4.0)
    src, dst = hero.flows(d, style.PALETTES["dark"])
    assert any(t[0] == "Searchers kept" for t in dst)
    assert any("negative" in s[0] for s in src)
    assert sum(s[1] for s in src) == pytest.approx(sum(t[1] for t in dst))


def test_unbalanced_destination_raises() -> None:
    d = dict(fixture_frames()["summary"]["lp"]["destination"])
    d["proposer_usd"] = 50.0
    with pytest.raises(ValueError, match="do not balance"):
        hero.flows(d, style.PALETTES["light"])


def test_social_card_is_1280_by_640(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path / "r", fixture_frames()))
    [path] = hero.social_card(r, tmp_path / "out")
    assert path.name == "00_hero.png" and Image.open(path).size == (1280, 640)


def test_ulpe_figures_writes_every_expected_file(tmp_path: Path) -> None:
    d = write_results(tmp_path / "results", fixture_frames())
    written = render.render_all(d, d / "figures")
    names = {p.name for p in written}
    stems = ["00_hero", "01_what_is_lvr", "02_stale_pool_episode", "03_pool_follows_binance",
             "04_markouts", "05_lvr_vs_volatility", "06_cumulative_fees_vs_lvr",
             "07_measured_vs_theory", "08_bots_keep", "09_every_position", "10_pnl_by_group",
             "11_jit_block", "12_lifetime"]
    assert [s for s, _ in render.FIGURES] == stems
    expected = {f"{s}.svg" for s in stems} | {f"{s}-dark.svg" for s in stems}
    assert names == expected | {"02_stale_pool_episode.gif", "00_hero.png"}
    assert {p.name for p in (d / "figures").iterdir()} == names
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_viz_hero.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `viz/hero.py`**

```python
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
    verts = [(x0, y0a), (xm, y0a), (xm, y1a), (x1, y1a), (x1, y1b), (xm, y1b), (xm, y0b),
             (x0, y0b), (x0, y0a)]
    codes = [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4, MplPath.LINETO,
             MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4, MplPath.CLOSEPOLY]
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
        ax.text(X_RIGHT + NODE_W + 0.02, y - h / 2, f"{label}  {usd(v)} · {pct(v / lvr)}",
                va="center", fontsize=9.5, color=p.ink, clip_on=False)
        right.append([y, y - h])
        y -= h + gap
    height = total * scale
    left, y = [], 0.5 + height / 2
    for label, v, c in sources:
        h = v * scale
        ax.add_patch(Rectangle((X_LEFT, y - h), NODE_W, h, color=c, lw=0,
                               hatch="///" if label.startswith("Paid") else None, fill=True))
        ax.text(X_LEFT - 0.02, y - h / 2, f"{label}\n{usd(v)}", va="center", ha="right",
                fontsize=9.5, color=c, fontweight="bold", clip_on=False)
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
        ax.add_patch(Rectangle((X_RIGHT - 0.012, y0), NODE_W + 0.024, h, fill=False,
                               hatch="xxx", edgecolor=p.muted, lw=0.6))
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
```

- [ ] **Step 4: Register**

In `viz/render.py` add `from uniswap_lp_economics.viz import hero`; make `("00_hero", hero.hero)`
the first entry of `FIGURES`, and append `hero.social_card` to `EXTRAS`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "viz: hero Sankey of where LVR goes, and the social card"
git push -q origin chart-redesign
```

---

### Task 12: Real render, README and methodology

**Files:**
- Modify: `README.md`, `docs/methodology.md`
- Regenerate: `results/figure_data/*`, `results/figures/*` (old PNGs removed by `ulpe figures`)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Regenerate the figure data and figures (offline)**

```bash
cd "/c/ABC/DeFI Test/uniswap-lp-economics"
uv run ulpe analyze      # writes results/figure_data/basis_hist.csv (minutes)
uv run ulpe lp           # writes the episode and JIT-block tables (about 10 min; run in background)
uv run python -I -c "from pathlib import Path; from uniswap_lp_economics import config; from uniswap_lp_economics.viz.render import render_all; print(len(render_all(config.RESULTS_DIR, config.RESULTS_DIR / 'figures', preview_dir=Path('C:/Users/enric/AppData/Local/Temp/claude/C--ABC-DeFI-Test/9143b708-43fb-429b-aecd-5e335f1fd579/scratchpad/preview'))))"
git status --short results
```

Expected: `ulpe analyze` and `ulpe lp` PASS with unchanged numbers (`git diff results/summary.json`
shows only provenance changes and key order); `results/figures/` holds 13 × 2 SVGs, the GIF and
`00_hero.png`, and no PNG charts from before.

- [ ] **Step 2: Check every render by eye**

Open every PNG in the preview directory (light and dark) and the GIF. For each, check: title true
for the real data (a title that overstates the data is changed to a true one, in the figure module,
with its test updated); no clipped or overlapping text; readable in dark mode; numbers match
`summary.json`. Fix in the figure modules, re-run the render command, repeat. Send the previews to
the user before committing.

- [ ] **Step 3: Reorder the README into the story**

Restructure `README.md` so the sections run:

1. Title, one-line description, badges (unchanged).
2. Hero: `<picture>` with `results/figures/00_hero-dark.svg` / `00_hero.svg`.
3. TL;DR findings 1–6 (text unchanged).
4. **What is LVR?** — figure 1, then figure 2 (embed the GIF below the static SVG with the line
   "Animated: `results/figures/02_stale_pool_episode.gif`").
5. **Does the pool follow Binance?** — figure 3 with the existing basis, episodes and lead-lag text.
6. **Who wins against the pool?** — figure 4 with the existing markout text and tables.
7. **How big is LVR, and when?** — figures 5, 6, 7 with the existing fees-vs-LVR text, tables and
   regime table.
8. **Do arbitrage bots keep the edge?** — figure 8 with the existing arbitrage and bot text.
9. **Who pays?** — figures 9, 10, 11, 12 with the existing LP P&L, JIT and lifetime text. State the
   "$10k" framing once: "USD per $10,000 of position value per month = bp/day × 30".
10. **Where LVR goes** — the existing destination text, referring back to the hero.
11. Data, method, limitations, reproduce, repo map, further reading, licence, disclaimer (existing
    sections), with: `ulpe figures` in the reproduce steps; `viz/`, `assets/fonts/` and
    `results/figure_data/` in the repo map; one line that `results/figures/00_hero.png` is the
    repository's social preview image (set by hand under Settings → General).

Every figure is embedded as:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="results/figures/05_lvr_vs_volatility-dark.svg">
  <img src="results/figures/05_lvr_vs_volatility.svg" alt="Daily LVR and swap fees against daily realised volatility, log-log, with fitted slopes and the break-even volatility">
</picture>
```

Remove every reference to the old PNG names (`grep -n "results/figures/.*png" README.md` must
return only `00_hero.png`) and to "Chart N" numbering; refer to figures by their chapter instead.
No finding's text or number changes.

- [ ] **Step 4: Methodology**

Add a section "Figures" to `docs/methodology.md` (before "Limitations of sub-project 3"):

```markdown
## Figures

`ulpe figures` renders every figure from `results/` only (`summary.json`, the results CSVs and
`results/figure_data/`), in light and dark SVG with text as outlines, so a re-render with unchanged
inputs changes no file. The style (palette, Inter font, title block) is in `viz/style.py`.

| Figure | Inputs |
|---|---|
| Hero: where the LVR on searcher swaps went | `summary.json` `lp.destination` |
| 1 What is LVR (schematic) | none |
| 2 A stale-pool episode (and GIF) | `figure_data/episode_blocks.csv`, `episode_cex.csv` |
| 3 The pool follows Binance | `figure_data/basis_hist.csv`, `episodes.csv`, `summary.json` `lead_lag` |
| 4 Markouts by flow | `markouts.csv` |
| 5 LVR and fees against volatility | `lvr_daily.csv` |
| 6 Cumulative fees vs LVR | `lvr_daily.csv`, `summary.json` `lp.daily` |
| 7 Measured vs theoretical LVR | `lvr_daily.csv` |
| 8 Do bots keep the edge | `summary.json` `arbitrage`, `bot_profit.csv` |
| 9 Every position | `positions.csv` |
| 10 P&L by group | `lp_groups.csv` |
| 11 One JIT block | `figure_data/jit_block.csv`, `positions.csv` |
| 12 Lifetime vs holding | `summary.json` `lp.lifetime*` |

**Episode selection (figure 2).** The day with the largest measured LVR (0 s; the earliest on
ties); within it, the 20-block stretch with the largest absolute Binance log move; the figure shows
32 blocks starting 4 blocks before that stretch (fewer at the day's edges).

**JIT block selection (figure 11).** Among JIT positions whose own transactions (mint and burn) also
hold a pool swap before the first liquidity add and one after the last removal, the one with the
largest P&L vs rebalancing (then the lowest block, then the id). Without such a position, the most
profitable JIT position, and the figure says so.

**"$10k" framing (figure 10).** P&L per $10,000 of time-weighted position value per 30 days =
`bp_per_day × 30`, since `bp_per_day` is P&L per 10⁴ of value per day.

**Line of best fit (figure 5).** Ordinary least squares of log USD per day on log annualised
volatility, over days with positive LVR and fees; the break-even is where the two fits cross.
```

Also update the spec's section 4 wording to match what was built: figure 3's gap survival is
computed from `episodes.csv` and its lead–lag from `summary.json`, figure 8's waterfall from
`summary.json` `arbitrage` (only `basis_hist.csv` is new on the sub-project 2 side), and the episode
window is "32 blocks starting 4 blocks before the stretch".

- [ ] **Step 5: Final gates and commit**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src
git add -A results README.md docs
git commit -m "Figures: real render in the new style; README reordered into the story"
git push -q origin chart-redesign
```
