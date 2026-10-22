"""Carried-forward pool: identity replay (check S2) and mode re-execution (spec 6.1-6.2)."""

import copy
import json
from pathlib import Path

import polars as pl
from lpworld import EVENT_SCHEMA, L, T, ev, oracle, world_end_us, world_inputs

from uniswap_lp_economics.io import read_exact
from uniswap_lp_economics.lp.analyze import LpInputs
from uniswap_lp_economics.lp.engine import iter_engine_rows
from uniswap_lp_economics.lp.state import FeeAccumulators, PoolState, step_values
from uniswap_lp_economics.lp.swapfees import build_swap_fees
from uniswap_lp_economics.strategy.cfpool import (
    CfInputs,
    CfRun,
    FixedFee,
    SwapInfo,
    prepare_inputs,
    reexecute,
    run_pool,
)
from uniswap_lp_economics.strategy.checks import check_s2
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
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
