"""The figure registry and `ulpe figures` (chart redesign spec section 3): every figure in light
and dark SVG, plus the extras (GIF, social card); stale figure files are removed."""

from collections.abc import Callable
from pathlib import Path

from matplotlib.figure import Figure

from uniswap_lp_economics import config
from uniswap_lp_economics.viz import what_is_lvr
from uniswap_lp_economics.viz.data import Results, load_results
from uniswap_lp_economics.viz.style import MODES, save_svg, theme

FigureFn = Callable[[Results], Figure]
ExtraFn = Callable[[Results, Path], list[Path]]

# (file stem, figure function), in README order; each chapter task appends its entries.
FIGURES: list[tuple[str, FigureFn]] = [
    ("01_what_is_lvr", what_is_lvr.concept),
    ("02_stale_pool_episode", what_is_lvr.episode),
]
EXTRAS: list[ExtraFn] = [what_is_lvr.episode_gif]
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
