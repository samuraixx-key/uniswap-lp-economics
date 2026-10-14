import json
from pathlib import Path

import polars as pl
import pytest
from lpworld import T0, US, world_inputs

from uniswap_lp_economics.lp import analyze as lp
from uniswap_lp_economics.lp.checks import check_l6
from uniswap_lp_economics.lp.pnl import HOUR_US, Edge, liquidity_path, position_spans


def test_lp_analysis_end_to_end(tmp_path: Path) -> None:
    inp = world_inputs()
    results, processed = tmp_path / "results", tmp_path / "processed"
    results.mkdir()
    (results / "summary.json").write_text(json.dumps({"swaps": 4, "lp": {"stale": 1}}))
    status = lp.lp_analysis(
        inp, results, processed, {"git_commit": "test"}, end_us=inp.window_end_us
    )
    assert status == "PASS", (results / "lp_checks.md").read_text(encoding="utf-8")
    for name in (
        "lp_pnl.md",
        "lvr_daily.csv",
        "vol_regimes.md",
        "lp_groups.csv",
        "lp_groups.md",
        "positions.csv",
        "lifetime.md",
    ):
        assert (results / name).exists(), name
    for name in lp.LP_FIGURES.values():
        assert (results / "figures" / name).exists(), name
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    assert summary["swaps"] == 4  # sub-project 2 keys are kept
    assert summary["lp"]["git_commit"] == "test"
    assert summary["lp"]["positions_window_active"] == 3
    assert "stale" not in summary["lp"]  # only the "lp" key is replaced (plan Ruling 10)
    assert summary["lp"]["collect_shortfalls"] == {"count": 0, "max_d0": 0, "max_d1": 0}
    assert summary["lp"]["n_excluded_carry"] == 0 == summary["lp"]["lifetime"]["n_excluded_carry"]
    assert any("L6" in name for name in summary["lp"]["checks"])
    positions = pl.read_csv(results / "positions.csv")
    assert set(positions["lp_type"].to_list()) == {"jit", "nft_wallet", "direct_other"}
    for name in (
        "swap_steps.parquet",
        "positions.parquet",
        "position_flows.parquet",
        "position_days.parquet",
        "lp_blocks.parquet",
    ):
        assert (processed / name).exists(), name


def test_failed_gate_writes_no_lp_results(tmp_path: Path) -> None:
    inp = world_inputs()
    inp.end_positions = inp.end_positions.with_columns(tokens_owed0=pl.lit(1, dtype=pl.Int128))
    results, processed = tmp_path / "results", tmp_path / "processed"
    status = lp.lp_analysis(
        inp, results, processed, {"git_commit": "test"}, end_us=inp.window_end_us
    )
    assert status == "FAIL"
    assert "L3" in (results / "lp_checks.md").read_text(encoding="utf-8")
    assert not (results / "lp_pnl.md").exists() and not processed.exists()


def test_l6_tolerance_and_identity() -> None:
    steps = pl.DataFrame(
        {
            "zero_for_one": [True, True],
            "lp_fee": [10, 10],
            "accrued": [True, True],
            "lvr_0": [1.0, 2.0],
            "block_number": [1, 2],
            "log_index": [0, 0],
        },
        schema={
            "zero_for_one": pl.Boolean,
            "lp_fee": pl.Int128,
            "accrued": pl.Boolean,
            "lvr_0": pl.Float64,
            "block_number": pl.Int64,
            "log_index": pl.Int64,
        },
    )
    accounts = pl.DataFrame(
        {"fees_raw0": [19], "fees_raw1": [0], "lvr_0": [3.0]},
        schema={"fees_raw0": pl.Int128, "fees_raw1": pl.Int128, "lvr_0": pl.Float64},
    )
    aligned = pl.DataFrame(
        {
            "block_number": [1, 2],
            "log_index": [0, 0],
            "markout_usd_0": [0.5, 1.5],
            "p_cex_0": [2000.0, 2000.0],
        }
    )
    swap_fees = pl.DataFrame(
        {
            "block_number": [1, 2],
            "log_index": [0, 0],
            "fee_token": ["USDC", "USDC"],
            "fee_raw": [500_000, 500_000],
        },
        schema={
            "block_number": pl.Int64,
            "log_index": pl.Int64,
            "fee_token": pl.String,
            "fee_raw": pl.Int128,
        },
    )
    assert check_l6(steps, accounts, aligned, swap_fees, 0).passed
    over = accounts.with_columns(fees_raw0=pl.lit(21, dtype=pl.Int128))
    assert not check_l6(steps, over, aligned, swap_fees, 0).passed  # more than the pool paid


def test_days_without_theory_stop_the_run(tmp_path: Path) -> None:
    inp = world_inputs()
    results, processed = tmp_path / "results", tmp_path / "processed"
    one_day = int(T0.timestamp()) * US + 86_400 * US  # Binance data ends before day 2
    with pytest.raises(ValueError, match="no theoretical LVR"):
        lp.lp_analysis(inp, results, processed, {"git_commit": "test"}, end_us=one_day)
    assert not (results / "lp_pnl.md").exists() and not processed.exists()


def test_hourly_grid_uses_utc_hour_starts() -> None:
    bs = pl.DataFrame(
        {"ts_us": [0, 5_000 * US], "sqrt_price_x96": [2**96, 2**97], "p_cex": [1.0, 4.0]},
        schema={
            "ts_us": pl.Int64,
            "sqrt_price_x96": pl.Int128,
            "p_cex": pl.Float64,
        },
    )
    grid = lp.hourly_grid(bs, 10 * US, 3 * HOUR_US)
    assert grid["ts_us"].to_list() == [HOUR_US, 2 * HOUR_US]
    # the price in force at each hour: the block at 0 s, then the block at 5,000 s
    assert grid["sqrt"].to_list() == [1.0, 2.0]
    assert grid["p_cex"].to_list() == [1.0, 4.0]
    assert lp.hourly_grid(bs, 10 * US, 20 * US).height == 0


def test_spans_and_liquidity_path_follow_event_order() -> None:
    start, end = Edge(1, 100, 0, 1.0), Edge(9, 900, 0, 1.0)
    accounts = pl.DataFrame(
        {
            "position_id": ["a", "b", "c"],
            "liquidity_start": [5, 0, 0],
            "liquidity_end": [5, 0, 3],
            "active": [True, True, False],
        },
        schema={
            "position_id": pl.String,
            "liquidity_start": pl.Int128,
            "liquidity_end": pl.Int128,
            "active": pl.Boolean,
        },
    )
    positions = pl.DataFrame(
        {"position_id": ["a", "b", "c"], "tick_lower": [0, 0, 0], "tick_upper": [10, 10, 10]}
    )
    flows = pl.DataFrame(
        {
            "position_id": ["b", "b", "b", "a"],
            "block_number": [2, 2, 5, 6],
            "log_index": [0, 1, 0, 0],
            "ts_us": [200, 200, 500, 600],
            "liquidity_delta": [4, -4, 7, 0],
        },
        schema={
            "position_id": pl.String,
            "block_number": pl.Int64,
            "log_index": pl.Int64,
            "ts_us": pl.Int64,
            "liquidity_delta": pl.Int128,
        },
    )
    spans = position_spans(positions, accounts, flows, start, end).sort("position_id")
    assert spans["position_id"].to_list() == ["a", "b"]  # inactive accounts are left out
    assert spans["t_start_us"].to_list() == [100, 200]  # open at start / first deposit
    assert spans["t_exit_us"].to_list() == [900, 200]  # open at end / last removal
    path = liquidity_path(accounts, flows, start).filter(pl.col("position_id") == "b")
    assert path["liquidity"].to_list() == [0, 4, 0, 7]  # same-timestamp changes in event order
