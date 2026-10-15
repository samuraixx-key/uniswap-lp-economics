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
