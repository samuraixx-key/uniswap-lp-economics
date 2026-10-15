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
        "05_lvr_vs_volatility",
        "06_cumulative_fees_vs_lvr",
        "07_measured_vs_theory",
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
