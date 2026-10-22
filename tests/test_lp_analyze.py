import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from lpworld import JIT_DIRECT_WEI, T0, US, WALLET, D, J, L, T, world_end_us, world_inputs

from uniswap_lp_economics.config import HOUR_US
from uniswap_lp_economics.lp import analyze as lp
from uniswap_lp_economics.lp import destination
from uniswap_lp_economics.lp.analyze import LpInputs
from uniswap_lp_economics.lp.checks import check_l6
from uniswap_lp_economics.lp.pnl import (
    Edge,
    liquidity_path,
    position_amounts,
    position_spans,
    usd,
)


def test_lp_analysis_end_to_end(tmp_path: Path) -> None:
    inp = world_inputs()
    results, processed = tmp_path / "results", tmp_path / "processed"
    results.mkdir()
    (results / "summary.json").write_text(json.dumps({"swaps": 4, "lp": {"stale": 1}}))
    status = lp.lp_analysis(inp, results, processed, {"git_commit": "test"}, end_us=world_end_us())
    assert status == "PASS", (results / "lp_checks.md").read_text(encoding="utf-8")
    for name in (
        "lp_pnl.md",
        "lvr_daily.csv",
        "vol_regimes.md",
        "lp_groups.csv",
        "lp_groups.md",
        "positions.csv",
        "lifetime.md",
        "lvr_destination.md",
    ):
        assert (results / name).exists(), name
    fd = results / "figure_data"
    blocks = pl.read_csv(fd / "episode_blocks.csv")
    assert blocks.columns == [
        "block_number",
        "ts_us",
        "pool_price",
        "p_cex",
        "lvr_0_usd",
        "has_searcher",
    ]
    assert blocks.height >= 1 and pl.read_csv(fd / "episode_cex.csv").height >= 1
    jit_block = pl.read_csv(fd / "jit_block.csv")
    assert jit_block.height >= 3 and set(jit_block["role"]) >= {"jit"}
    assert jit_block["full_pattern"].to_list()[0] is False  # no own swaps around the world's JIT
    assert not (results / "figures").exists()
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    assert summary["swaps"] == 4  # sub-project 2 keys are kept
    assert summary["lp"]["git_commit"] == "test"
    assert summary["lp"]["positions_window_active"] == 3
    assert "stale" not in summary["lp"]  # only the "lp" key is replaced (plan Ruling 10)
    for name in (
        "reference_robustness.csv",
        "reference_robustness.md",
        "block_timing.csv",
        "block_timing.md",
    ):
        assert (results / name).exists(), name
    rob = pl.read_csv(results / "reference_robustness.csv")
    primary = rob.filter((pl.col("reference") == "binance_last_trade") & (pl.col("offset_s") == 0))
    assert primary["fees_minus_lvr_usd"][0] == pytest.approx(summary["lp"]["fees_minus_lvr_usd"])
    r = summary["lp"]["robustness"]
    assert set(r) == {
        "crossing_offset_s",
        "timing",
        "fees_minus_lvr_at_median_timing_usd",
        "largest_reference_shift_0s_usd",
        "protocol_fees_share_of_gap",
        "proxy_quality",
    }
    assert r["timing"]["n_timed"] == 2 and r["timing"]["p50_ms"] == 1000
    assert pl.read_csv(results / "block_timing.csv").height == 2
    checks = (results / "lp_checks.md").read_text(encoding="utf-8")
    assert "| R6 robustness table reproduces the headline (reported) | reported |" in checks
    assert summary["lp"]["collect_shortfalls"] == {"count": 0, "max_d0": 0, "max_d1": 0}
    assert summary["lp"]["n_excluded_carry"] == 0 == summary["lp"]["lifetime"]["n_excluded_carry"]
    assert any("L6" in name for name in summary["lp"]["checks"])
    assert "destination" in summary["lp"]
    assert summary["lp"]["destination_limitation"] == destination.LIMITATION_TEXT
    checks_text = (results / "lp_checks.md").read_text(encoding="utf-8")
    assert all(f"R{i}" in checks_text for i in range(1, 6))
    rows = [line for line in checks_text.splitlines() if line.startswith("| ")]
    assert all("| reported |" in r for r in rows if r.startswith("| R"))  # not gated
    assert all("| PASS |" in r for r in rows if r.startswith("| L"))
    l1 = next(v for k, v in summary["lp"]["checks"].items() if k.startswith("L1"))
    assert l1["engine_unmatched"] == 0
    r1 = next(v for k, v in summary["lp"]["checks"].items() if k.startswith("R1"))
    assert r1["by_round"]["seen"]["paid"]["found"] == 1  # the world's relay row: block 7, paid
    jit = summary["lp"]["jit_per_swap"]
    assert jit["positions"] == 1 and jit["swaps"] >= 1
    assert jit["pnl_rebal_usd_per_swap"] == pytest.approx(
        positions_jit_rebal(results) / jit["swaps"]
    )
    assert "JIT per swap" in (results / "lp_pnl.md").read_text(encoding="utf-8")
    daily = summary["lp"]["daily"]
    assert daily["fees_minus_lvr_usd"] == pytest.approx(summary["lp"]["fees_minus_lvr_usd"])
    assert daily["fees_minus_lvr_ci_lo_usd"] <= daily["fees_minus_lvr_ci_hi_usd"]
    assert summary["lp"]["lifetime_by_life"] and summary["lp"]["lifetime_by_width"]
    dest = summary["lp"]["destination"]
    # Chain (0 s): LVR on searcher steps = LP fees + protocol fees + searchers' gross markout.
    assert dest["lvr_on_searcher_swaps_usd"] == pytest.approx(
        dest["fees_on_searcher_swaps_usd"]
        + dest["protocol_fees_on_searcher_swaps_usd"]
        + dest["searcher_gross_usd"]
    )
    shares = [v for k, v in dest.items() if k.startswith("share_") and "pool" not in k]
    assert sum(shares) == pytest.approx(1.0)  # the chain accounts for all searcher-step LVR
    assert dest["pool_lvr_0_usd"] == pytest.approx(dest["lvr_on_searcher_swaps_usd"])
    assert dest["n_swaps_no_other_logs_row"] == dest["n_swaps_null_costs"] == 0
    assert any(k.startswith("R2") for k in summary["lp"]["checks"])
    assert dest["lvr_on_other_flows_usd"] == 0.0 and dest["multi_pool_gross_usd"] == 0.0
    # 100,000 gas at 1 gwei base fee, 0 priority: burned = 1e-4 ETH per swap, none paid on top.
    assert dest["gas_burned_usd"] == pytest.approx(
        sum(1e-4 * p for p in inp.aligned["p_cex_0"].to_list())
    )
    # The one builder payment beyond gas: the JIT transaction's direct payment (block 9, which
    # also swaps), counted here as the swap's and in positions.csv as the JIT position's cost.
    p9 = inp.aligned.filter(pl.col("block_number") == 9)["p_cex_0"][0]
    proposer_share = 5 * 10**14 / (10**15 + JIT_DIRECT_WEI)  # last_value / (priority + direct)
    assert dest["builder_margin_usd"] == pytest.approx(
        JIT_DIRECT_WEI / 1e18 * p9 * (1 - proposer_share)
    )
    sens = dest["sensitivity_self_built"]  # every world block is paid: the split does not move
    assert sens["self_built_blocks"] == 0 and sens["builder_paid_self_built_usd"] == 0.0
    assert sens["proposer_usd"] == pytest.approx(dest["proposer_usd"])
    dest_text = (results / "lvr_destination.md").read_text(encoding="utf-8")
    assert "Sensitivity" in dest_text and "primary" in dest_text
    builder_paid = dest["proposer_usd"] + dest["builder_margin_usd"]
    assert builder_paid == pytest.approx(JIT_DIRECT_WEI / 1e18 * p9)
    assert dest["searcher_kept_usd"] == pytest.approx(
        dest["single_pool_gross_usd"] - dest["gas_burned_usd"] - builder_paid
    )
    positions = pl.read_csv(results / "positions.csv")
    assert set(positions["lp_type"].to_list()) == {"jit", "nft_wallet", "direct_other"}
    _assert_world_numbers(inp, summary["lp"], positions)
    for name in (
        "swap_steps.parquet",
        "positions.parquet",
        "position_flows.parquet",
        "position_days.parquet",
        "lp_blocks.parquet",
    ):
        assert (processed / name).exists(), name


def positions_jit_rebal(results: Path) -> float:
    positions = pl.read_csv(results / "positions.csv")
    return float(positions.filter(pl.col("lp_type") == "jit")["pnl_rebal_usd"].sum())


def _assert_world_numbers(inp: LpInputs, summary: dict[str, Any], positions: pl.DataFrame) -> None:
    """Expected values from the world's own constants (lpworld), not from the run's output."""
    fee_rate = 500 / 1_000_000
    swaps_usdc = [10**9, 2 * 10**9, 10**9, 10**9]  # the four swaps; no protocol fee in the world
    flash0, flash1 = 1_000_000, 10**15  # paid by the flash at block 8
    pool0 = sum(round(x * fee_rate) for x in swaps_usdc) + flash0
    l6 = next(v for k, v in summary["checks"].items() if k.startswith("L6"))
    assert l6["pool_lp_fees_raw"] == [pool0, flash1]
    p_flash = inp.aligned.filter(pl.col("block_number") == 7)["p_cex_0"][0]  # last swap before it
    expected_fees = pool0 / 1e6 + flash1 / 1e18 * p_flash
    assert summary["lp_fees_usd"] == pytest.approx(expected_fees, rel=1e-12)

    # Gas: 100,000 gas at 1 gwei, at the Binance price of the block, per position its tx touched.
    price = dict(inp.blocks_state.select("block_number", "p_cex").iter_rows())
    unit = 100_000 * 10**9 / 1e18
    gas = positions.select("position_id", "gas_usd").to_dicts()
    by_id = {r["position_id"]: r["gas_usd"] for r in gas}
    nft, jit = "nft:1", f"direct:{J}:{T - 10}:{T + 10}:0"
    direct = f"direct:{D}:{T - 10}:{T + 10}:0"
    assert by_id[nft] == pytest.approx(unit * (price[6] + price[10]))  # mint tx, burn+collect tx
    assert by_id[jit] == pytest.approx(unit * price[9])
    assert by_id[direct] == 0.0  # D changed nothing in the window
    paid = dict(positions.select("position_id", "direct_usd").iter_rows())
    assert paid[jit] == pytest.approx(JIT_DIRECT_WEI / 1e18 * price[9])
    assert paid[nft] == 0.0 == paid[direct]
    assert summary["lp_direct_payments_usd"] == pytest.approx(paid[jit])
    own = summary["jit_own_swaps"]
    assert own["jit_txs"] == 1 == own["jit_txs_with_own_swaps"]  # block 9 also swaps
    assert own["direct_usd_in_txs_with_own_swaps"] == pytest.approx(paid[jit])

    # The identities pnl.window_pnl defines.
    for r in positions.iter_rows(named=True):
        cost = r["gas_usd"] + r["direct_usd"]
        assert r["pnl_rebal_usd"] == pytest.approx(r["fee_usd"] - r["lvr_0"] - cost)
        assert r["pnl_rebal_12_usd"] == pytest.approx(r["fee_usd"] - r["lvr_12"] - cost)
    assert positions["fee_usd"].sum() <= summary["lp_fees_usd"] + 1e-9  # floors never overpay

    # D was open before the window: its time-weighted value comes from the hourly grid, not
    # from the first-deposit fallback (its value at the window start).
    first = inp.blocks_state.sort("block_number").row(0, named=True)
    fallback = usd(
        *position_amounts(L, T - 10, T + 10, int(inp.meta["sqrt_price_x96"])), first["p_cex"]
    )
    d_twv = positions.filter(pl.col("position_id") == direct)["twv_usd"][0]
    assert d_twv != pytest.approx(fallback, rel=1e-9)
    assert d_twv > 0
    assert summary["share_positions_beat_hold_window"] is not None
    assert summary["lifetime"]["share_beat_hold"] is not None
    assert WALLET in positions["lp"].to_list()


def test_failed_gate_writes_no_lp_results(tmp_path: Path) -> None:
    inp = world_inputs()
    inp.end_positions = inp.end_positions.with_columns(tokens_owed0=pl.lit(1, dtype=pl.Int128))
    results, processed = tmp_path / "results", tmp_path / "processed"
    status = lp.lp_analysis(inp, results, processed, {"git_commit": "test"}, end_us=world_end_us())
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
    assert not (results / "lp_checks.md").exists()  # nothing is written before every number is


def test_missing_summary_stops_before_any_write(tmp_path: Path) -> None:
    inp = world_inputs()
    results, processed = tmp_path / "results", tmp_path / "processed"
    with pytest.raises(FileNotFoundError, match="ulpe analyze"):
        lp.lp_analysis(inp, results, processed, {"git_commit": "test"}, end_us=world_end_us())
    assert not (results / "lp_checks.md").exists() and not processed.exists()


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


def test_l6_shortfall_beyond_the_tolerance_fails() -> None:
    steps = pl.DataFrame(
        {
            "zero_for_one": [True, True],
            "lp_fee": [10, 10],
            "accrued": [True, True],
            "lvr_0": [1.0, 2.0],
        },
        schema={
            "zero_for_one": pl.Boolean,
            "lp_fee": pl.Int128,
            "accrued": pl.Boolean,
            "lvr_0": pl.Float64,
        },
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

    def accounts(fees0: int) -> pl.DataFrame:
        return pl.DataFrame(
            {"fees_raw0": [fees0], "fees_raw1": [0], "lvr_0": [3.0]},
            schema={"fees_raw0": pl.Int128, "fees_raw1": pl.Int128, "lvr_0": pl.Float64},
        )

    # tolerance = 2 accrued steps + 0 flows + 2 x 1 account = 4 raw units below the pool's 20
    assert check_l6(steps, accounts(16), aligned, swap_fees, 0).passed
    assert not check_l6(steps, accounts(15), aligned, swap_fees, 0).passed
    assert check_l6(steps, accounts(15), aligned, swap_fees, 1).passed  # a window flow adds one
