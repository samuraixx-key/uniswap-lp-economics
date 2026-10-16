from pathlib import Path

import numpy as np
import polars as pl
import pytest
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, render, style, who_pays


def test_registered() -> None:
    stems = [s for s, _ in render.FIGURES]
    for stem in ("09_every_position", "10_pnl_by_group", "12_lifetime"):
        assert stem in stems
    assert (
        stems.index("08_bots_keep")
        < stems.index("09_every_position")
        < stems.index("10_pnl_by_group")
    )


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
        pl.when(pl.col("position_id") == "w1")
        .then(0.0)
        .otherwise(pl.col("twv_usd"))
        .alias("twv_usd")
    )
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        style.svg_bytes(who_pays.every_position(r))


def _many_positions(n: int) -> pl.DataFrame:
    rng = np.random.default_rng(7)
    types = np.array(["jit", "nft_wallet", "lp_vault", "nft_contract"])
    return pl.DataFrame(
        {
            "position_id": [f"p{i}" for i in range(n)],
            "lp_type": types[rng.integers(0, len(types), n)],
            "twv_usd": 10 ** rng.uniform(2, 7, n),
            "fee_usd": rng.uniform(0, 100, n),
            "lvr_0": rng.uniform(0, 200, n),
            "gas_usd": rng.uniform(0, 5, n),
            "direct_usd": np.zeros(n),
            "pnl_rebal_usd": rng.normal(0, 500, n),
        }
    )


def test_every_position_rasterizes_the_dots_and_stays_deterministic(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["positions"] = _many_positions(20_000)
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        first = style.svg_bytes(who_pays.every_position(r))
        second = style.svg_bytes(who_pays.every_position(r))
    assert b"<image" in first
    assert len(first) < 800_000  # as vectors, 20,000 dots alone take about 1.5 MB
    assert first == second


def test_symlog_footnote_and_axis_share_one_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(who_pays, "SYMLOG_LINTHRESH_USD", 25.0)
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = who_pays.every_position(r)
        texts = " ".join(t.get_text() for t in fig.texts)
        linthresh = fig.axes[0].yaxis.get_transform().linthresh
    assert "linear within ±$25" in texts and linthresh == 25.0
