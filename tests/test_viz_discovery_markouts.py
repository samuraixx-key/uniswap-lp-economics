from pathlib import Path

import polars as pl
import pytest
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


def test_negative_markout_labels_use_the_minus_sign(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = viz_markouts.markouts(r)
    labels = [t.get_text() for ax in fig.axes for t in ax.texts if t.get_text().endswith(" bp")]
    assert "−6.0 bp" in labels  # aggregators at 0 s
    assert not any("-" in t for t in labels)


def test_lead_lag_ticks_are_whole_blocks(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["summary"]["lead_lag"]["cross_correlation"] = [
        {"lag_blocks": k, "corr": 0.1 * (k > 0), "n": 100} for k in range(-5, 6)
    ]  # as in the real results, where the default ticks fall on half blocks
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        fig = viz_discovery.pool_follows_binance(r)
        fig.canvas.draw()
        c = fig.axes[2]
        lo, hi = c.get_xlim()
        ticks = [t for t in c.get_xticks() if lo <= t <= hi]
    assert ticks and all(float(t).is_integer() for t in ticks)


def test_basis_footnote_uses_the_histogram_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(viz_discovery, "BASIS_HIST_RANGE_BP", 40.0)
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        texts = " ".join(t.get_text() for t in viz_discovery.pool_follows_binance(r).texts)
    assert "clipped to ±40 bp" in texts
