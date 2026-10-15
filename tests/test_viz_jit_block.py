from pathlib import Path

import polars as pl
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import data, jit_block, render, style


def test_registered_between_10_and_12() -> None:
    stems = [s for s, _ in render.FIGURES]
    assert stems.index("10_pnl_by_group") + 1 == stems.index("11_jit_block")
    assert stems.index("11_jit_block") + 1 == stems.index("12_lifetime")


def test_jit_block_labels_events_and_totals(tmp_path: Path) -> None:
    r = data.load_results(write_results(tmp_path, fixture_frames()))
    with style.theme("light"):
        fig = jit_block.jit_block(r)
        texts = " ".join(t.get_text() for t in fig.texts + fig.axes[0].texts)
    assert "Block 12" in texts and "Operator's swap" in texts and "JIT adds" in texts
    assert "P&L vs rebalancing" in texts and "$11" in texts


def test_empty_jit_block_says_so(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["jit_block"] = frames["jit_block"].head(0)
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("dark"):
        fig = jit_block.jit_block(r)
        texts = " ".join(t.get_text() for t in fig.texts + fig.axes[0].texts)
        style.svg_bytes(fig)
    assert "no JIT position" in texts


def test_fallback_title_without_the_full_pattern(tmp_path: Path) -> None:
    frames = fixture_frames()
    frames["jit_block"] = frames["jit_block"].with_columns(full_pattern=pl.lit(False))
    r = data.load_results(write_results(tmp_path, frames))
    with style.theme("light"):
        fig = jit_block.jit_block(r)
        title = fig.texts[0].get_text()
    assert title.startswith("Inside the most profitable JIT block")
