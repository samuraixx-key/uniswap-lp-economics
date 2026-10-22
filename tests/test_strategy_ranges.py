"""Range attribution of recorded steps (spec 5.1) and check S1 against the engine (spec 5.2)."""

import math
from datetime import date

import polars as pl
import pytest
from lpworld import EVENT_SCHEMA, SNAP, J, L, T, ev, oracle
from test_strategy_cfpool import NO_BLOCKS, _world

from uniswap_lp_economics.lp.engine import iter_engine_rows
from uniswap_lp_economics.lp.state import step_values
from uniswap_lp_economics.strategy.cfpool import (
    CF_STEP_SCHEMA,
    CfInputs,
    FixedFee,
    SwapInfo,
    run_pool,
)
from uniswap_lp_economics.strategy.checks import check_s1
from uniswap_lp_economics.strategy.ranges import attribute, held_from_flows
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import SwapRun, swap

P0 = 2000.0
DAY = date(2026, 7, 1)
COLS = (
    "block_number",
    "log_index",
    "step",
    "day",
    "zero_for_one",
    "p0",
    "liquidity",
    "sqrt_start",
    "sqrt_end",
    "tick_start",
    "fee_usd",
    "lvr_0",
    "accrued",
)
SCHEMA = {c: CF_STEP_SCHEMA[c] for c in COLS}


def _steps(run: SwapRun, zero_for_one: bool) -> pl.DataFrame:
    """One swap's steps at block 1; tick_start is only read for steps that do not move."""
    rows = []
    for i, s in enumerate(run.steps):
        _, _, fee_usd, lvr0 = step_values(s.fee, s.amount_in, s.amount_out, zero_for_one, 0, P0)
        rows.append(
            (1, 0, i, DAY, zero_for_one, P0, s.liquidity, s.sqrt_start, s.sqrt_end, T)
            + (fee_usd, lvr0, s.liquidity > 0)
        )
    return pl.DataFrame(rows, schema=SCHEMA, orient="row")


def _held(lo: int, hi: int, liquidity: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "seg": [0],
            "start_block": [0],
            "start_log": [0],
            "end_block": [100],
            "end_log": [0],
            "tick_lower": [lo],
            "tick_upper": [hi],
            "liquidity": [liquidity],
        }
    )


def _book() -> TickBook:
    b = TickBook(tick=T, sqrt_price_x96=sqrt_at(T), liquidity=0)
    b.apply_mint(T - 200, T + 200, L)
    return b


@pytest.mark.parametrize(
    ("zero_for_one", "lo", "hi", "amount"),
    [(True, T - 40, T - 20, 10**11), (False, T + 20, T + 40, 5 * 10**19)],
)
def test_partial_step_matches_a_split_swap(
    zero_for_one: bool, lo: int, hi: int, amount: int
) -> None:
    ell = L // 10**9
    whole = swap(_book(), zero_for_one, amount)
    path = sorted((sqrt_at(T), whole.sqrt_price_x96))
    assert path[0] < sqrt_at(lo) and sqrt_at(hi) < path[1]  # the swap passes the whole range
    split_book = _book()
    split_book.apply_mint(lo, hi, ell)
    fee = lvr = 0.0
    for s in swap(split_book, zero_for_one, amount).steps:
        a, b = sorted((s.sqrt_start, s.sqrt_end))
        if sqrt_at(lo) <= a and b <= sqrt_at(hi):
            _, _, f, v = step_values(s.fee, s.amount_in, s.amount_out, zero_for_one, 0, P0)
            fee += f * ell / s.liquidity
            lvr += v * ell / s.liquidity
    got = attribute(_steps(whole, zero_for_one), _held(lo, hi, float(ell)))
    assert got.height >= 1
    assert got["share"].to_list() == [ell / L] * got.height
    assert math.isclose(got["fee_usd"].sum(), fee, rel_tol=1e-6)
    assert math.isclose(got["lvr_0"].sum(), lvr, rel_tol=1e-6)


def test_full_inside_uses_recorded_values() -> None:
    steps = _steps(swap(_book(), True, 10**10), True)
    ell = 3.0e15
    got = attribute(steps, _held(T - 200, T + 200, ell))
    assert got.height == steps.height
    assert got["fee_usd"].to_list() == [f * (ell / L) for f in steps["fee_usd"]]
    assert got["lvr_0"].to_list() == [v * (ell / L) for v in steps["lvr_0"]]


def test_flash_at_bounds() -> None:
    s = sqrt_at(T)
    flash = pl.DataFrame(
        [(8, 0, 0, DAY, True, P0, L, s, s, T, 0.5, 0.0, True)], schema=SCHEMA, orient="row"
    )
    at_lower = attribute(flash, _held(T, T + 10, 1e15))  # the price sits on the lower tick
    assert at_lower["fee_usd"].to_list() == [0.5 * (1e15 / L)]
    assert at_lower["lvr_0"].to_list() == [0.0]
    assert attribute(flash, _held(T - 10, T, 1e15)).height == 0  # on the upper tick: out
    no_liquidity = flash.with_columns(liquidity=pl.lit(0, pl.Int128), accrued=pl.lit(False))
    assert attribute(no_liquidity, _held(T, T + 10, 1e15)).height == 0


def test_tick_start_after_a_crossing_in_both_directions() -> None:
    book = TickBook(tick=T, sqrt_price_x96=sqrt_at(T), liquidity=0)
    book.apply_mint(T - 10, T + 10, L)
    book.apply_mint(T - 30, T + 30, L)
    events = pl.DataFrame(
        [  # down across T - 10, then up across T - 10 and T + 10
            ev(7, 0, "swap", amount0=8 * 10**10, amount1=-1, sqrt_price_x96=sqrt_at(T), tick=T),
            ev(7, 1, "swap", amount0=-1, amount1=7 * 10**19, sqrt_price_x96=sqrt_at(T), tick=T),
        ],
        schema=EVENT_SCHEMA,
    )
    info = SwapInfo(P0, "exact_input", False)
    ci = CfInputs(
        rows=list(iter_engine_rows(events)),
        book=book,
        fee_protocol=0,
        blocks=NO_BLOCKS,
        swaps={(7, 0): info, (7, 1): info},
    )
    steps = run_pool(ci, FixedFee(500), replace=False, keep_steps=True).steps
    assert steps is not None
    after = (
        steps.sort("block_number", "log_index", "step")
        .with_columns(next_tick=pl.col("tick_start").shift(-1).over("block_number", "log_index"))
        .filter(pl.col("crossed_tick").is_not_null() & pl.col("next_tick").is_not_null())
    )
    crossed = after.select("zero_for_one", "crossed_tick").rows()
    assert (True, T - 10) in crossed and (False, T - 10) in crossed and (False, T + 10) in crossed
    expected = pl.when(pl.col("zero_for_one")).then(pl.col("crossed_tick") - 1)
    assert after.select((pl.col("next_tick") == expected.otherwise("crossed_tick")).all()).item()


def test_s1_on_the_world() -> None:
    inp, run, _ = _world()
    assert run.steps is not None
    ledger, _ = oracle(inp.pool_history, inp.npm_history)
    data = ledger.data
    positions = (
        ledger.accounts_frame()
        .filter("active")
        .join(data.positions.select("position_id", "tick_lower", "tick_upper"), on="position_id")
    )
    flows = data.flows
    r = check_s1(run.steps, positions, flows, SNAP)
    assert r.name == "S1 range attribution vs engine"
    assert r.passed, (r.summary, r.mismatches)
    assert r.summary["positions"] == positions.height == 3
    assert r.summary["failures"] == 0
    # the JIT position, minted and burned around the block-9 swap, holds that swap and nothing else
    jit = data.positions.filter(pl.col("owner") == J)["position_id"].item()
    held = held_from_flows(flows, SNAP).filter(pl.col("position_id") == jit)
    assert held.select("start_block", "start_log", "end_block", "end_log").rows() == [(9, 1, 9, 3)]
    got = attribute(run.steps, held.with_columns(tick_lower=pl.lit(T - 10), tick_upper=T + 10))
    assert got.select("block_number", "log_index").unique().rows() == [(9, 1)]
    # one position's engine fee off by 1e-6 relative fails the check
    top = positions.sort("fee_usd")["position_id"][-1]
    bumped = positions.with_columns(
        fee_usd=pl.when(pl.col("position_id") == top)
        .then(pl.col("fee_usd") * (1 + 1e-6))
        .otherwise("fee_usd")
    )
    r = check_s1(run.steps, bumped, flows, SNAP)
    assert not r.passed
    assert r.summary["worst_position"] == top
    assert r.summary["failures"] >= 1
