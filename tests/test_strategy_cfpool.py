"""Carried-forward pool: identity replay (check S2) and mode re-execution (spec 6.1-6.2)."""

import copy
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from lpworld import EVENT_SCHEMA, LAST, L, T, ev, oracle, ts, world_end_us, world_inputs

from uniswap_lp_economics.align import reference_at, reference_table
from uniswap_lp_economics.config import US
from uniswap_lp_economics.io import read_exact
from uniswap_lp_economics.lp.analyze import LpInputs
from uniswap_lp_economics.lp.engine import iter_engine_rows
from uniswap_lp_economics.lp.state import FeeAccumulators, PoolState, step_values
from uniswap_lp_economics.lp.swapfees import build_swap_fees
from uniswap_lp_economics.strategy.cfpool import (
    CfInputs,
    CfRun,
    FixedFee,
    MoveFee,
    OracleFee,
    SwapInfo,
    VolatilityFee,
    prepare_inputs,
    reexecute,
    rule_grid,
    run_pool,
)
from uniswap_lp_economics.strategy.checks import (
    check_s2,
    check_s3,
    min_profit_gas,
    replaced_keys,
    sandwich_legs,
)
from uniswap_lp_economics.strategy.params import (
    CALIBRATION_TOL,
    JULY_START_US,
    MAX_FEE_BP,
    MIN_FEE_BP,
    REPORT_START_US,
    bp_to_pips,
)
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3math import sqrt_price_x96_to_eth_price
from uniswap_lp_economics.v3swap import swap

FIX = Path(__file__).parent / "fixtures"
NO_BLOCKS = pl.DataFrame(
    schema={
        "block_number": pl.Int64,
        "ts_us": pl.Int64,
        "day": pl.Date,
        "base_fee_wei": pl.Int64,
        "p_ref_0": pl.Float64,
        "p_ref_1": pl.Float64,
    }
)


def test_step_values_matches_poolstate() -> None:
    fee_protocol = 4 + (5 << 4)  # a cut on both tokens
    for zero_for_one, amount in ((True, 6 * 10**10), (False, 3 * 10**19)):
        book = TickBook(tick=T, sqrt_price_x96=sqrt_at(T), liquidity=0)
        state = PoolState(book, FeeAccumulators(), fee_protocol)
        state.mint(T - 10, T + 10, L)
        state.mint(T - 30, T + 30, L)  # the swaps cross a tick: two steps or more
        r = swap(book, zero_for_one, amount)
        records = state.swap(1, 0, r, zero_for_one, r.sqrt_price_x96, r.tick, 2000.0, None, "x", 0)
        assert len(records) >= 2
        for s, rec in zip(r.steps, records, strict=True):
            got = step_values(s.fee, s.amount_in, s.amount_out, zero_for_one, fee_protocol, 2000.0)
            assert got == (rec.protocol_fee, rec.lp_fee, rec.fee_usd, rec.lvr_0)
            assert rec.protocol_fee > 0


def _world() -> tuple[LpInputs, CfRun, pl.DataFrame]:
    inp = world_inputs()
    _, engine = oracle(inp.pool_history, inp.npm_history)
    ci = prepare_inputs(
        inp.events,
        inp.ticks,
        inp.meta,
        inp.aligned,
        inp.swap_fees,
        inp.blocks_state,
        inp.blocks,
        inp.trades,
        set(),
        world_end_us(),
    )
    return inp, run_pool(ci, FixedFee(500), replace=False, keep_steps=True), engine.steps


def test_identity_replay_reproduces_the_world() -> None:
    inp, run, swap_steps = _world()
    r = check_s2(run, swap_steps, inp.blocks_state, inp.aligned)
    assert r.name == "S2 identity replay"
    assert r.passed, (r.summary, r.mismatches)
    assert r.summary["mismatches"] == 0
    assert r.summary["steps_compared"] == swap_steps.height > 0
    assert r.summary["blocks_compared"] == inp.events["block_number"].n_unique()
    assert run.counts["mode_exact_output"] == 1
    assert run.counts["mode_to_price"] == 1
    assert run.counts["mode_exact_input"] == 4
    assert FixedFee(500).name == "fixed_5bp" and FixedFee(250).name == "fixed_2.5bp"
    assert run.steps is not None
    flash = run.steps.filter(pl.col("source") == "flash")
    assert flash.height == 2 and (flash["sqrt_start"] == flash["sqrt_end"]).all()
    # a step starts where the previous one ended, and the first at the book's state
    kept = run.steps.filter(pl.col("source") == "kept").sort("block_number", "log_index", "step")
    first = kept.row(0, named=True)
    assert first["sqrt_start"] == int(inp.meta["sqrt_price_x96"])
    assert first["tick_start"] == int(inp.meta["tick"])


def test_identity_replay_on_the_real_fixture() -> None:
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    ticks = read_exact(FIX / "fixture_ticks.parquet")
    events = read_exact(FIX / "fixture_events.parquet")
    fee_protocol = int(meta["fee_protocol"])
    modes = build_swap_fees(events, TickBook.from_snapshot(ticks, meta), fee_protocol)
    assert modes["mode"].null_count() == 0
    ci = CfInputs(
        rows=list(iter_engine_rows(events)),
        book=TickBook.from_snapshot(ticks, meta),
        fee_protocol=fee_protocol,
        blocks=NO_BLOCKS,
        swaps={
            (b, li): SwapInfo(2000.0, m, False)
            for b, li, m in modes.select("block_number", "log_index", "mode").iter_rows()
        },
    )
    run = run_pool(ci, FixedFee(500), replace=False, keep_steps=True)
    assert run.steps is not None and run.counts["to_price_skipped"] == 0
    got = (
        run.steps.filter(pl.col("source") == "kept")
        .sort("block_number", "log_index", "step")
        .group_by("block_number", "log_index", maintain_order=True)
        .agg(
            amount_in=(pl.col("amount_in") + pl.col("fee")).sum(),
            amount_out=pl.col("amount_out").sum(),
            sqrt=pl.col("sqrt_end").last(),
        )
    )
    logged = events.filter(
        (pl.col("event") == "swap") & ((pl.col("amount0") > 0) | (pl.col("amount1") > 0))
    ).select(
        "block_number",
        "log_index",
        amount_in=pl.max_horizontal("amount0", "amount1"),
        amount_out=pl.lit(0, pl.Int128) - pl.min_horizontal("amount0", "amount1"),
        sqrt="sqrt_price_x96",
    )
    assert logged.height > 0 and got.height == logged.height
    both = logged.join(got, on=["block_number", "log_index"], how="left", suffix="_cf")
    bad = both.filter(
        pl.col("amount_in").ne_missing(pl.col("amount_in_cf"))
        | pl.col("amount_out").ne_missing(pl.col("amount_out_cf"))
        | pl.col("sqrt").ne_missing(pl.col("sqrt_cf"))
    )
    assert bad.height == 0, bad.head(5)


def test_passed_limit_executes_nothing() -> None:
    book = TickBook(tick=T, sqrt_price_x96=sqrt_at(T), liquidity=0)
    book.apply_mint(T - 10, T + 10, L)
    limit = sqrt_at(T + 5)  # a zero-for-one swap's limit, already above the book's price
    assert reexecute(book, "to_price", 10**9, -(10**17), limit, 500) is None
    assert reexecute(book, "no_input", 0, 0, book.sqrt_price_x96, 500) is None
    events = pl.DataFrame(
        [
            ev(7, 0, "swap", amount0=10**9, amount1=-(10**17), sqrt_price_x96=limit, tick=T + 5),
            ev(7, 1, "swap", amount0=0, amount1=0, sqrt_price_x96=limit, tick=T + 5),
        ],
        schema=EVENT_SCHEMA,
    )
    before = copy.deepcopy(book)
    ci = CfInputs(
        rows=list(iter_engine_rows(events)),
        book=book,
        fee_protocol=0,
        blocks=NO_BLOCKS,
        swaps={
            (7, 0): SwapInfo(2000.0, "to_price", False),
            (7, 1): SwapInfo(2000.0, "no_input", False),
        },
    )
    run = run_pool(ci, FixedFee(500), replace=False, keep_steps=True)
    assert run.counts["to_price_skipped"] == 1 and run.counts["no_input"] == 1
    assert run.counts["mode_to_price"] == 0
    assert run.steps is not None and run.steps.height == 0
    assert run.block_end is not None
    assert run.block_end.rows() == [(7, before.sqrt_price_x96, before.tick, before.liquidity)]
    assert ci.book == before


def test_s2_fails_on_one_wrong_step() -> None:
    inp, run, swap_steps = _world()
    k = swap_steps.height // 2
    wrong = swap_steps.with_columns(
        fee=pl.when(pl.int_range(pl.len()) == k).then(pl.col("fee") + 1).otherwise(pl.col("fee"))
    )
    r = check_s2(run, wrong, inp.blocks_state, inp.aligned)
    assert r.passed is False and r.summary["mismatches"] == 1
    b, li, s = swap_steps.row(k)[:3]
    first = r.summary["first_mismatch"]
    assert (first["block_number"], first["log_index"], first["step"]) == (b, li, s)


def _blocks(rows: list[tuple[int, float | None]]) -> pl.DataFrame:
    """Window blocks at ts(b) with a 1 gwei base fee and the same reference at 0 s and +1 s."""
    return pl.DataFrame(
        [(b, int(ts(b).timestamp()) * US, ts(b).date(), 10**9, p, p) for b, p in rows],
        schema=NO_BLOCKS.schema,
        orient="row",
    )


def _wide_book() -> TickBook:
    book = TickBook(tick=T, sqrt_price_x96=sqrt_at(T), liquidity=0)
    book.apply_mint(T - 600, T + 600, L)
    return book


def test_fee_rules() -> None:
    vol = VolatilityFee(2, 25)
    p = 2000.0
    assert vol.block_fee_pips(p, None) == bp_to_pips(MIN_FEE_BP)
    for _ in range(2000):
        p *= math.exp(3e-4)
        vol.end_block(p)
    assert abs(vol.block_fee_pips(p, None) - bp_to_pips(6)) <= 1
    move = MoveFee(1)
    assert move.block_fee_pips(2000.0, None) == bp_to_pips(5)
    move.end_block(2000.0 * math.exp(7e-4))
    assert move.block_fee_pips(2000.0 * math.exp(7e-4), None) == bp_to_pips(12)
    oracle_fee = OracleFee()
    assert oracle_fee.block_fee_pips(2000.0 * math.exp(20e-4), 2000.0) == bp_to_pips(20)
    assert oracle_fee.block_fee_pips(2000.0 * math.exp(-20e-4), 2000.0) == bp_to_pips(20)
    assert oracle_fee.block_fee_pips(2000.0 * math.exp(2e-4), 2000.0) == bp_to_pips(5)
    # every rule asked for 500 bp charges the cap
    assert oracle_fee.block_fee_pips(2000.0 * math.exp(500e-4), 2000.0) == bp_to_pips(MAX_FEE_BP)
    big = MoveFee(1)
    big.block_fee_pips(2000.0, None)
    big.end_block(2000.0 * math.exp(495e-4))
    assert big.block_fee_pips(0.0, None) == bp_to_pips(MAX_FEE_BP) == bp_to_pips(100)
    vol_big = VolatilityFee(1, 1)  # one step of a half-life-1 EWMA: sigma = 1000 bp / sqrt(2)
    vol_big.block_fee_pips(2000.0, None)
    vol_big.end_block(2000.0 * math.exp(0.1))
    assert vol_big.block_fee_pips(0.0, None) == bp_to_pips(MAX_FEE_BP)
    grid = rule_grid()
    names = [r.name for r in grid]
    assert len(grid) == 24 and len(set(names)) == 24
    assert {"fixed_5bp", "fixed_2.5bp", "vol_k2_h25", "move_k0.5", "oracle"} <= set(names)


def test_arbitrage_closes_the_gap() -> None:
    book = _wide_book()
    p_ref = sqrt_price_x96_to_eth_price(book.sqrt_price_x96) / (1 - 0.003)  # pool 30 bp under
    ci = CfInputs(rows=[], book=book, fee_protocol=0, blocks=_blocks([(7, p_ref)]), swaps={})
    run = run_pool(ci, FixedFee(500), replace=True, min_profit_gas=0, keep_steps=True)
    assert run.block_end is not None and run.steps is not None
    after = sqrt_price_x96_to_eth_price(run.block_end["sqrt_price_x96"][0])
    assert after == pytest.approx(p_ref * (1 - 0.0005) * (1 - 0.0001), abs=1e-9)
    assert run.daily["n_arb"].to_list() == [1] and run.counts["arb_trades"] == 1
    assert set(run.steps["source"]) == {"arb"} and set(run.steps["log_index"]) == {-1}
    assert run.daily["lvr_arb_usd"][0] > 0 and run.daily["fee_arb_total_usd"][0] > 0
    none = run_pool(ci, FixedFee(500), replace=True, min_profit_gas=10**30)
    assert none.counts["below_min_profit"] == 1 and none.counts["arb_trades"] == 0
    assert none.daily["n_arb"].to_list() == [0]
    assert none.block_end is not None
    assert none.block_end["sqrt_price_x96"][0] == book.sqrt_price_x96
    blind = CfInputs(rows=[], book=book, fee_protocol=0, blocks=_blocks([(7, None)]), swaps={})
    counts = run_pool(blind, FixedFee(500), replace=True, min_profit_gas=0).counts
    assert counts["no_reference_blocks"] == 1 and counts["arb_trades"] == 0
    with pytest.raises(ValueError, match="min_profit_gas"):
        run_pool(ci, FixedFee(500), replace=True)


def test_replaced_swaps_are_skipped_and_counted() -> None:
    book = _wide_book()
    p_ref = sqrt_price_x96_to_eth_price(book.sqrt_price_x96) * 1.002
    events = pl.DataFrame(
        [
            ev(7, 0, "swap", amount0=10**9, amount1=-(10**17), sqrt_price_x96=0, tick=T),
            ev(7, 1, "swap", amount0=2 * 10**9, amount1=-(10**17), sqrt_price_x96=0, tick=T),
            ev(7, 2, "flash", paid0=10**6, paid1=10**15),
        ],
        schema=EVENT_SCHEMA,
    )
    ci = CfInputs(
        rows=list(iter_engine_rows(events)),
        book=book,
        fee_protocol=0,
        blocks=_blocks([(7, p_ref)]),
        swaps={
            (7, 0): SwapInfo(2000.0, "exact_input", True),
            (7, 1): SwapInfo(2000.0, "exact_input", False),
        },
    )
    run = run_pool(ci, FixedFee(500), replace=True, min_profit_gas=0, keep_steps=True)
    assert run.steps is not None
    kept = run.steps.filter(pl.col("source") == "kept")
    assert set(kept["log_index"]) == {1}
    assert run.counts["replaced"] == 1 and run.counts["mode_exact_input"] == 1
    assert run.counts["arb_trades"] == 1
    accrued = run.steps.filter(pl.col("accrued"))
    assert set(accrued["source"]) == {"arb", "kept", "flash"}
    d = run.daily.row(0, named=True)
    expected = (accrued["fee_usd"] / accrued["liquidity"].cast(pl.Float64)).sum()
    assert d["fee_arb_pl"] + d["fee_kept_pl"] == pytest.approx(expected, rel=1e-12)
    kept_lvr = (kept["lvr_0"] / kept["liquidity"].cast(pl.Float64)).sum()
    assert d["lvr_kept_pl"] == pytest.approx(kept_lvr, rel=1e-12)
    assert d["fee_kept_usd"] == pytest.approx(
        run.steps.filter(pl.col("source") != "arb")["fee_usd"].sum(), rel=1e-12
    )
    # identity mode: the replaced swap is re-executed like any other
    same = run_pool(ci, FixedFee(500), replace=False)
    assert same.counts["replaced"] == 0 and same.counts["mode_exact_input"] == 2


def test_daily_is_zero_filled() -> None:
    day3 = datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=2)
    swap0 = {"amount0": 10**9, "amount1": -(10**17), "sqrt_price_x96": 0, "tick": T}
    events = pl.DataFrame(
        [ev(7, 0, "swap", **swap0), ev(30, 0, "swap", **swap0, block_timestamp=day3)],
        schema=EVENT_SCHEMA,
    )
    ci = CfInputs(
        rows=list(iter_engine_rows(events)),
        book=_wide_book(),
        fee_protocol=0,
        blocks=NO_BLOCKS,
        swaps={k: SwapInfo(2000.0, "exact_input", False) for k in ((7, 0), (30, 0))},
    )
    daily = run_pool(ci, FixedFee(500), replace=False).daily
    assert daily["day"].to_list() == [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
    assert all(v == 0 for v in daily.row(1)[1:])
    assert daily["n_blocks"].to_list() == [1, 0, 1]
    assert daily["fee_pips_sum"].to_list() == [500, 0, 500]
    assert daily["fee_kept_usd"][0] > 0 and daily["fee_kept_usd"][2] > 0


def test_prepare_inputs_blocks_frame() -> None:
    inp = world_inputs()
    end_us = int(ts(LAST).timestamp()) * US + US // 2  # the last block's +1 s is past the data
    ci = prepare_inputs(
        inp.events,
        inp.ticks,
        inp.meta,
        inp.aligned,
        inp.swap_fees,
        inp.blocks_state,
        inp.blocks,
        inp.trades,
        set(),
        end_us,
    )
    b = ci.blocks
    assert b["block_number"].to_list() == sorted(inp.blocks_state["block_number"].to_list())
    ref = reference_table(inp.trades)
    t = inp.blocks_state.sort("block_number")["ts_us"]
    assert b["p_ref_0"].to_list() == reference_at(t, ref, end_us)["price"].to_list()
    assert b["p_ref_1"].to_list() == reference_at(t + US, ref, end_us)["price"].to_list()
    assert b["p_ref_1"][-1] is None and b["p_ref_0"][-1] is not None
    assert b["p_ref_0"].null_count() == 0
    assert b["base_fee_wei"].to_list() == [10**9] * b.height
    days = [datetime.fromtimestamp(x / US, UTC).date() for x in t.to_list()]
    assert b["day"].to_list() == days and len(set(days)) == 2


def test_unreproduced_swap_is_skipped_and_counted() -> None:
    inp = world_inputs()
    fees = inp.swap_fees.filter(~((pl.col("block_number") == 7) & (pl.col("log_index") == 0)))
    ci = prepare_inputs(
        inp.events,
        inp.ticks,
        inp.meta,
        inp.aligned,
        fees,
        inp.blocks_state,
        inp.blocks,
        inp.trades,
        set(),
        world_end_us(),
    )
    assert ci.swaps[(7, 0)].mode == "unreproduced"
    run = run_pool(ci, FixedFee(500), replace=False, keep_steps=True)
    assert run.counts["unreproduced"] == 1 and run.counts["no_input"] == 0
    assert run.steps is not None
    assert run.steps.filter((pl.col("block_number") == 7) & (pl.col("log_index") == 0)).height == 0


def _measured_frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Three July swaps and one August swap (3, 0), every one with LVR and a fee."""
    keys = {"block_number": [1, 1, 2, 3], "log_index": [0, 1, 0, 0]}
    july = JULY_START_US + 3600 * US
    aligned = pl.DataFrame(
        {**keys, "p_cex_0": [2000.0] * 4, "t0_us": [july, july, july, REPORT_START_US]}
    )
    swap_steps = pl.DataFrame({**keys, "step": [0] * 4, "lvr_0": [3.0, 1.0, 100.0, 50.0]})
    swap_fees = pl.DataFrame(
        {
            **keys,
            "fee_token": ["USDC", "WETH", "USDC", "USDC"],
            "fee_raw": [2 * 10**6, 10**15, 10**9, 7 * 10**6],
        }
    )
    return aligned, swap_steps, swap_fees


def _s3_run(lvr: float, fee: float, august: float = 0.0) -> CfRun:
    """Two July days sharing lvr and fee, and an August day carrying `august` of each."""
    daily = pl.DataFrame(
        {
            "day": [date(2026, 7, 1), date(2026, 7, 31), date(2026, 8, 1)],
            "lvr_arb_usd": [lvr / 2, lvr / 2, august],
            "fee_arb_total_usd": [fee / 2, fee / 2, august],
        }
    )
    return CfRun(daily=daily, counts={}, steps=None, block_end=None)


def test_s3_pass_and_fail() -> None:
    aligned, swap_steps, swap_fees = _measured_frames()
    replaced = {(1, 0), (1, 1)}  # (2, 0) is kept: not part of the calibration
    lvr, fee = 4.0, 2.0 + 2.0  # 1e15 wei at 2,000 USD = 2 USD

    def run(lvr_x: float, fee_x: float) -> CfRun:
        return _s3_run(lvr * lvr_x, fee * fee_x)

    ok = check_s3(run(1.10, 0.95), swap_steps, aligned, swap_fees, replaced, run(1.3, 1.0))
    assert ok.name == "S3 calibration (July)" and ok.passed and ok.reported
    assert ok.summary["lvr_ratio"] == pytest.approx(1.10)
    assert ok.summary["fee_ratio"] == pytest.approx(0.95)
    assert ok.summary["lvr_ratio_1s"] == pytest.approx(1.3)
    assert ok.summary["fee_ratio_1s"] == pytest.approx(1.0)
    assert ok.summary["measured_lvr_usd"] == pytest.approx(lvr)
    assert ok.summary["measured_fee_usd"] == pytest.approx(fee)
    assert ok.summary["tolerance"] == CALIBRATION_TOL
    bad = check_s3(run(1.20, 1.0), swap_steps, aligned, swap_fees, replaced, run(1.0, 1.0))
    assert not bad.passed and bad.summary["lvr_ratio"] == pytest.approx(1.20)
    assert [m["measure"] for m in bad.mismatches] == ["lvr"]


def test_s3_counts_july_only() -> None:
    aligned, swap_steps, swap_fees = _measured_frames()
    replaced = {(1, 0), (1, 1), (3, 0)}  # (3, 0) is an August replaced swap
    model = _s3_run(4.0 * 1.05, 4.0, august=1000.0)  # a full-window run: August present
    r = check_s3(model, swap_steps, aligned, swap_fees, replaced, model)
    assert r.summary["measured_lvr_usd"] == pytest.approx(4.0)
    assert r.summary["measured_fee_usd"] == pytest.approx(4.0)
    assert r.summary["model_lvr_usd"] == pytest.approx(4.2)
    assert r.summary["model_fee_usd"] == pytest.approx(4.0)
    assert r.summary["replaced_swaps"] == 2
    assert r.passed


def test_sandwich_pattern() -> None:
    a, b, c = "0xa", "0xb", "0xc"
    aligned = pl.DataFrame(
        {
            "block_number": [1, 1, 1, 2, 2, 3, 3, 3],
            "log_index": [0, 3, 9, 0, 1, 0, 1, 2],
            "sender": [a, b, a, a, a, c, b, c],
            "zero_for_one": [True, False, False, True, False, True, True, True],
            "markout_usd_0": [5.0, 1.0, -8.0, 2.0, 2.0, 1.0, 1.0, 1.0],
            "notional_usd": [100.0, 50.0, 100.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "is_top_bot": [False, True, False, False, False, True, True, True],
        }
    )
    every = set(aligned.select("block_number", "log_index").iter_rows())
    # block 1: A buy, B, A sell; block 2: A buy, A sell, nothing between; block 3: same direction
    got = sandwich_legs(aligned, every)
    assert got["legs"] == 2 and got["gross_usd"] == pytest.approx(-3.0)
    assert got["notional_share"] == pytest.approx(200.0 / 300.0)
    assert got["non_top_legs"] == 2 and got["non_top_gross_usd"] == pytest.approx(-3.0)
    only_buy = sandwich_legs(aligned, {(1, 0)})
    assert only_buy["legs"] == 1 and only_buy["notional_share"] == pytest.approx(1.0)
    nothing_between = aligned.filter(pl.col("block_number") == 2)
    assert sandwich_legs(nothing_between, {(2, 0), (2, 1)})["legs"] == 0
    # A buy, B, A buy, A sell: the first buy pairs with the sell across B; the second does not
    later = pl.DataFrame(
        {
            "block_number": [4] * 4,
            "log_index": [0, 1, 2, 3],
            "sender": [a, b, a, a],
            "zero_for_one": [True, False, True, False],
            "markout_usd_0": [1.0, 2.0, 4.0, 8.0],
            "notional_usd": [1.0] * 4,
            "is_top_bot": [True] * 4,
        }
    )
    got = sandwich_legs(later, set(later.select("block_number", "log_index").iter_rows()))
    assert got["legs"] == 2 and got["gross_usd"] == pytest.approx(9.0)
    assert got["non_top_legs"] == 0


def test_replaced_keys_and_min_profit_gas() -> None:
    aligned = pl.DataFrame(
        {
            "block_number": [1, 1, 2, 3, 4, 5],
            "log_index": [0, 1, 0, 0, 0, 0],
            "tx_hash": ["t1", "t1", "t2", "t3", "t4", "t5"],
            "flow_label": ["searcher"] * 5 + ["other_contract"],
            "receipt_gas_used": [100, 100, 300, 200, 900, 50],
            "t0_us": [JULY_START_US] * 4 + [JULY_START_US + 10 * US, JULY_START_US],
        }
    )
    logs = pl.DataFrame({"tx_hash": ["t1", "t2", "t4", "t5"], "other_logs": [0, 0, 0, 0]})
    replaced = replaced_keys(aligned, logs)
    assert replaced == {(1, 0), (1, 1), (2, 0), (4, 0)}  # t3 has no row: kept; t5 not a searcher
    # distinct July transactions t1 (100) and t2 (300); t4 is past the end
    assert min_profit_gas(aligned, replaced, JULY_START_US + 5 * US) == 200
    assert min_profit_gas(aligned, {(1, 0), (1, 1)}, JULY_START_US + 5 * US) == 100
