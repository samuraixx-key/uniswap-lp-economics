from pathlib import Path
from typing import Any

from matplotlib.figure import Figure
from matplotlib.text import Text
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, render, strategy, style

CAVEAT = "ignores how other traders would react"


def draw(tmp_path: Path, name: str, frames: dict[str, Any] | None = None) -> Figure:
    r = data.load_results(write_results(tmp_path, frames or fixture_frames()))
    with style.theme("light"):
        fig = getattr(strategy, name)(r)
        style.svg_bytes(fig)
    return fig


def framed(fig: Figure, gid: str) -> str:
    return next(t.get_text() for t in fig.texts if t.get_gid() == gid).replace("\n", " ")


def texts(fig: Figure) -> list[str]:
    return [t.get_text() for t in fig.findobj(Text)]


def points(fig: Figure, gid: str) -> int:
    return sum(
        len(c.get_offsets()) for ax in fig.axes for c in ax.collections if c.get_gid() == gid
    )


def test_range_title_claims_nothing_beyond_the_verdict() -> None:
    assert strategy.title_range("holds", 0.068).startswith(
        "No range or rebalancing rule moves fees ÷ LVR by more than 0.07"
    )
    for verdict in ("fails", "inconclusive"):
        t = strategy.title_range(verdict, 0.068)
        assert "0.07" in t and "No range" not in t
    assert strategy.title_range("inconclusive", 0.068).startswith("Inconclusive")


def test_fee_title_states_x_and_y_and_flags_model_only() -> None:
    t = strategy.title_fee(18.0, 0.31, False)
    assert "about 18 bp" in t and "31%" in t and not t.startswith("Model only:")
    assert strategy.title_fee(18.0, 0.31, True).startswith("Model only:")
    for x, y in ((None, 0.3), (18.0, None), (None, None)):
        assert "about" not in strategy.title_fee(x, y, False)
    assert strategy.title_fee(None, None, True).startswith("Model only:")


def test_every_figure_carries_the_counterfactual_caveat(tmp_path: Path) -> None:
    for name in ("range_test", "fee_curves", "hedge_risk"):
        assert CAVEAT in framed(draw(tmp_path / name, name), "source"), name


def test_registry_ends_with_the_three_figures() -> None:
    stems = [s for s, _ in render.FIGURES]
    assert stems[-3:] == ["14_range_test", "15_fee_curves", "16_hedge"]


def test_range_figure_hollows_flagged_cells_and_draws_nothing_else(tmp_path: Path) -> None:
    fig = draw(tmp_path, "range_test")
    assert framed(fig, "title").startswith("Inconclusive")
    # widths 10 and 100 are flagged for each of the 3 rules; no static cell, no full range,
    # no $100k row
    assert points(fig, "flagged") == 6 and points(fig, "counted") == 6
    hollow = [c for c in fig.axes[0].collections if c.get_gid() == "flagged"]
    assert all(c.get_facecolor().shape[0] == 0 or c.get_facecolor()[0][3] == 0 for c in hollow)
    assert any("hollow" in t.lower() and "5%" in t for t in texts(fig))
    assert "Δ" in fig.axes[0].get_ylabel()


def test_fee_figure_is_model_only_and_marks_x_and_y(tmp_path: Path) -> None:
    fig = draw(tmp_path, "fee_curves")
    title = framed(fig, "title")
    assert title.startswith("Model only:") and "about 9 bp" in title and "43%" in title
    assert "model-only" in framed(fig, "source").lower()
    labels = texts(fig)
    assert any(t.startswith("X ") and "9 bp" in t for t in labels)
    assert any("oracle" in t for t in labels)
    assert [h.number for h in style.panel_headers(fig)] == [1, 2]


def test_fee_figure_draws_only_the_zero_offset_rows(tmp_path: Path) -> None:
    fig = draw(tmp_path, "fee_curves")
    curve = next(ln for ln in fig.axes[0].get_lines() if ln.get_gid() == "fixed")
    assert curve.get_xdata().tolist() == [1.0, 5.0, 10.0, 20.0, 100.0]  # not the +1 s rows


def test_fee_figure_without_model_only_says_so_nowhere(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["summary"]["strategy"]["fee_model_only"] = False
    fig = draw(tmp_path, "fee_curves", frames)
    assert not framed(fig, "title").startswith("Model only:")
    assert "model-only" not in framed(fig, "source").lower()


def test_hedge_figure_uses_five_bp_rows_never_and_the_benchmark(tmp_path: Path) -> None:
    fig = draw(tmp_path, "hedge_risk")
    assert [h.number for h in style.panel_headers(fig)] == [1, 2]
    # per panel: never, daily, hourly, drift at 5 bp, and the benchmark
    assert points(fig, "hedge") == 10
    labels = texts(fig)
    assert any("unhedged" in t for t in labels) and any("benchmark" in t for t in labels)
