from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl
import pytest
from matplotlib.figure import Figure

from uniswap_lp_economics.lp import figures


def test_lp_figures_render_even_when_empty(tmp_path: Path) -> None:
    empty = pl.DataFrame()
    figures.fees_vs_lvr_daily(empty, tmp_path / "a.png")
    figures.measured_vs_theory(empty, tmp_path / "b.png")
    figures.regime_chart(empty, tmp_path / "c.png")
    figures.group_chart(empty, tmp_path / "d.png")
    figures.lifetime_chart(empty, empty, tmp_path / "e.png")
    assert len(list(tmp_path.glob("*.png"))) == 5


def test_daily_chart_with_data(tmp_path: Path) -> None:
    daily = pl.DataFrame(
        {
            "day": [date(2026, 7, 1), date(2026, 7, 2)],
            "fees_usd": [1.0, 2.0],
            "lvr_0": [0.5, 3.0],
            "lvr_12": [0.4, 2.5],
            "lvr_0_searcher": [0.4, 2.0],
            "theory_1s": [0.6, 2.2],
            "theory_arb": [0.3, 1.1],
        }
    )
    figures.fees_vs_lvr_daily(daily, tmp_path / "a.png")
    figures.measured_vs_theory(daily, tmp_path / "b.png")
    assert (tmp_path / "a.png").stat().st_size > 0


def test_group_chart_survives_bounds_on_the_wrong_side(tmp_path: Path) -> None:
    # A bootstrap interval of a ratio of sums need not contain the point estimate.
    groups = pl.DataFrame(
        {
            "grouping": ["lp_type", "width_bucket"],
            "group": ["jit", "<50"],
            "bp_per_day": [5.0, -2.0],
            "ci_lo_bp": [6.0, -1.0],
            "ci_hi_bp": [9.0, -3.0],
        }
    )
    figures.group_chart(groups, tmp_path / "d.png")
    assert (tmp_path / "d.png").stat().st_size > 0


def test_destination_waterfall(tmp_path: Path) -> None:
    figures.destination_waterfall({}, tmp_path / "w0.png")
    d = {
        "pool_lvr_0_usd": 110.0,
        "lvr_on_other_flows_usd": 10.0,
        "share_fees": 0.4,
        "lvr_on_searcher_swaps_usd": 100.0,
        "fees_on_searcher_swaps_usd": 40.0,
        "protocol_fees_on_searcher_swaps_usd": 5.0,
        "searcher_gross_usd": 55.0,
        "multi_pool_gross_usd": 5.0,
        "single_pool_gross_usd": 50.0,
        "gas_burned_usd": 5.0,
        "builder_margin_usd": 10.0,
        "proposer_usd": 25.0,
        "searcher_kept_usd": 10.0,
    }
    figures.destination_waterfall(d, tmp_path / "w1.png")
    assert (tmp_path / "w1.png").stat().st_size > 0


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[Figure]:
    figs: list[Figure] = []
    monkeypatch.setattr(figures, "save_figure", lambda fig, path: figs.append(fig))
    return figs


def test_group_chart_plots_jit_on_its_own_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    figs = _capture(monkeypatch)
    groups = pl.DataFrame(
        {
            "grouping": ["lp_type", "lp_type", "lp_type", "width_bucket"],
            "group": ["jit", "nft_wallet", "lp_vault", "<50"],
            "bp_per_day": [5000.0, -1.4, -1.6, 2.0],
            "ci_lo_bp": [1000.0, -1.8, -3.0, -10.0],
            "ci_hi_bp": [9000.0, -1.1, -1.2, 20.0],
        }
    )
    figures.group_chart(groups, Path("unused.png"))
    axes = figs[0].axes
    labels = [[t.get_text() for t in ax.get_xticklabels()] for ax in axes]
    assert labels[0] == ["nft_wallet", "lp_vault"]  # the other LP types, on a readable scale
    assert labels[1] == ["jit"]
    assert labels[2] == ["<50"]
    assert axes[0].get_ylim()[0] > -10 and axes[0].get_ylim()[1] < 10
    plt.close(figs[0])


def test_destination_labels_stay_below_the_top_of_the_axes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    figs = _capture(monkeypatch)
    d = {
        "pool_lvr_0_usd": 3700.0,
        "lvr_on_other_flows_usd": -440.0,
        "lvr_on_searcher_swaps_usd": 4140.0,
        "fees_on_searcher_swaps_usd": 1976.0,
        "share_fees": 0.48,
        "proposer_usd": 790.0,
        "share_proposer": 0.19,
    }
    figures.destination_waterfall(d, Path("unused.png"))
    ax = figs[0].axes[0]
    fig = figs[0]
    fig.canvas.draw()
    top = ax.get_window_extent().y1
    texts = [t for t in ax.texts if t.get_text()]
    assert texts and all(t.get_window_extent().y1 < top for t in texts)
    plt.close(fig)
