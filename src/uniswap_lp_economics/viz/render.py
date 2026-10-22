"""The figure registry and `ulpe figures`: light SVGs, the GIF and the social card.

Stale exports are removed on regeneration.
"""

from collections.abc import Callable
from pathlib import Path

from matplotlib.figure import Figure

from uniswap_lp_economics import config
from uniswap_lp_economics.viz import bots, fees_vs_lvr, hero, what_is_lvr, who_pays
from uniswap_lp_economics.viz import discovery as viz_discovery
from uniswap_lp_economics.viz import jit_block as viz_jit_block
from uniswap_lp_economics.viz import markouts as viz_markouts
from uniswap_lp_economics.viz import robustness as viz_robustness
from uniswap_lp_economics.viz import strategy as viz_strategy
from uniswap_lp_economics.viz.data import Results, load_results
from uniswap_lp_economics.viz.style import save_svg, theme

FigureFn = Callable[[Results], Figure]
ExtraFn = Callable[[Results, Path], list[Path]]

# (file stem, figure function), in README order; each chapter task appends its entries.
FIGURES: list[tuple[str, FigureFn]] = [
    ("00_hero", hero.hero),
    ("01_what_is_lvr", what_is_lvr.concept),
    ("02_stale_pool_episode", what_is_lvr.episode),
    ("03_pool_follows_binance", viz_discovery.pool_follows_binance),
    ("04_markouts", viz_markouts.markouts),
    ("05_lvr_vs_volatility", fees_vs_lvr.lvr_vs_volatility),
    ("06_cumulative_fees_vs_lvr", fees_vs_lvr.cumulative),
    ("07_measured_vs_theory", fees_vs_lvr.measured_vs_theory),
    ("08_bots_keep", bots.bots_keep),
    ("09_every_position", who_pays.every_position),
    ("10_pnl_by_group", who_pays.pnl_by_group),
    ("11_jit_block", viz_jit_block.jit_block),
    ("12_lifetime", who_pays.lifetime),
    ("13_reference_and_timing", viz_robustness.reference_and_timing),
    ("14_range_test", viz_strategy.range_test),
    ("15_fee_curves", viz_strategy.fee_curves),
    ("16_hedge", viz_strategy.hedge_risk),
]
EXTRAS: list[ExtraFn] = [what_is_lvr.episode_gif, hero.social_card]
FIGURE_SUFFIXES = {".svg", ".png", ".gif"}
PREVIEW_DPI = 110


def render_all(results_dir: Path, out_dir: Path, preview_dir: Path | None = None) -> list[Path]:
    """Render every figure into out_dir; with preview_dir, also PNG copies for review."""
    r = load_results(results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for stem, fn in FIGURES:
        with theme("light"):
            fig = fn(r)
            if preview_dir is not None:
                preview_dir.mkdir(parents=True, exist_ok=True)
                fig.savefig(preview_dir / f"{stem}.png", dpi=PREVIEW_DPI)
            save_svg(fig, out_dir / f"{stem}.svg")
        written.append(out_dir / f"{stem}.svg")
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
