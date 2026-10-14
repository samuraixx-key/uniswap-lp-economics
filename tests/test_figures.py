from pathlib import Path

import polars as pl

from uniswap_lp_economics import figures

BY_LABEL = pl.DataFrame(
    {
        "flow_label": ["searcher", "searcher", "uniswap_router", "uniswap_router"],
        "horizon_s": [0, 12, 0, 12],
        "mean_bp": [2.0, 1.0, -3.0, None],
        "ci_lo_bp": [1.5, 0.5, -4.0, None],
        "ci_hi_bp": [2.5, 1.5, -2.0, None],
    }
)
SERIES = pl.DataFrame({"basis_bp": [-3.0, 0.0, 7.0, None]})
EPISODES = pl.DataFrame({"duration_s": [12.0, 24.0, 120.0]})
SUMMARY = pl.DataFrame({"closer": ["searcher", "cex"], "share_gap_weight": [0.8, 0.2]})
WATERFALL = {
    "available_usd": 2e6,
    "captured_searchers_usd": 1.5e6,
    "top_bot_single_pool_gross_usd": 1e6,
    "gas_burned_usd": 1e5,
    "priority_fee_usd": 2e5,
    "coinbase_usd": 5e5,
    "kept_usd": 2e5,
}
XC = pl.DataFrame({"lag_blocks": [-1, 0, 1], "corr": [0.0, 0.1, 0.9]})
BOTS = pl.DataFrame(
    {"sender": ["0x" + "b0" * 20, "TOTAL"], "gross_usd": [5e4, 5e4], "kept_usd": [1e4, 1e4]}
)


def _draw_all(
    tmp_path: Path,
    by_label: pl.DataFrame,
    series: pl.DataFrame,
    episodes: pl.DataFrame,
    summary: pl.DataFrame,
    w: dict[str, float],
    xc: pl.DataFrame,
    bots: pl.DataFrame,
) -> list[Path]:
    paths = [tmp_path / f"{i}.png" for i in range(1, 7)]
    figures.markout_curves(by_label, paths[0])
    figures.basis_histogram(series, paths[1], 5.0)
    figures.episode_chart(episodes, summary, paths[2])
    figures.waterfall_chart(w, paths[3])
    figures.cross_correlation_chart(xc, paths[4])
    figures.bot_profit_chart(bots, paths[5])
    return paths


def test_figures_write_pngs(tmp_path: Path) -> None:
    for p in _draw_all(tmp_path, BY_LABEL, SERIES, EPISODES, SUMMARY, WATERFALL, XC, BOTS):
        assert p.stat().st_size > 1000, p


def test_figures_handle_empty_inputs(tmp_path: Path) -> None:
    paths = _draw_all(
        tmp_path,
        BY_LABEL.head(0),
        SERIES.head(0),
        EPISODES.head(0),
        SUMMARY.head(0),
        {},
        XC.head(0),
        BOTS.head(0),
    )
    assert all(p.exists() for p in paths)
