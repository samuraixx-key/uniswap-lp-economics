from datetime import date
from pathlib import Path

import polars as pl

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
