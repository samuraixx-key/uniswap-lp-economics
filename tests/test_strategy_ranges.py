"""Range attribution of recorded steps (spec 5.1) and check S1 against the engine (spec 5.2)."""

import math
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest
from lpworld import EVENT_SCHEMA, SNAP, US, J, L, T, ev, oracle, world_end_us
from test_strategy_cfpool import NO_BLOCKS, _world

from uniswap_lp_economics.config import HOUR_US, NPM_ADDRESS
from uniswap_lp_economics.lp.analyze import hourly_grid
from uniswap_lp_economics.lp.engine import iter_engine_rows
from uniswap_lp_economics.lp.state import step_values
from uniswap_lp_economics.strategy.cfpool import (
    CF_STEP_SCHEMA,
    CfInputs,
    CfRun,
    FixedFee,
    SwapInfo,
    prepare_inputs,
    run_pool,
)
from uniswap_lp_economics.strategy.checks import check_s1
from uniswap_lp_economics.strategy.params import PRIMARY_CAPITAL, RULES, TAKER_FEE_BP
from uniswap_lp_economics.strategy.ranges import (
    LpCosts,
    StrategyResult,
    attribute,
    held_from_flows,
    lp_costs,
    peak_share,
    range_ticks,
    score,
    segments,
)
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import SwapRun, swap

P0 = 2000.0
FULL = 887_270  # the widest ticks on the 10-tick spacing
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
    [
        (True, T - 40, T - 20, 10**11),
        (False, T + 20, T + 40, 5 * 10**19),
        (True, -FULL, T - 20, 10**11),  # wide ranges: the far bound passes Int128
        (False, T + 20, FULL, 5 * 10**19),
    ],
)
def test_partial_step_matches_a_split_swap(
    zero_for_one: bool, lo: int, hi: int, amount: int
) -> None:
    ell = L // 10**9
    whole = swap(_book(), zero_for_one, amount)
    path = sorted((sqrt_at(T), whole.sqrt_price_x96))
    assert any(path[0] < sqrt_at(t) < path[1] for t in (lo, hi))  # a bound inside the path
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


@pytest.mark.parametrize(("lo", "hi"), [(T - 200, T + 200), (-FULL, FULL)])
def test_full_inside_uses_recorded_values(lo: int, hi: int) -> None:
    steps = _steps(swap(_book(), True, 10**10), True)
    ell = 3.0e15
    got = attribute(steps, _held(lo, hi, ell))
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


# --- Task 5: segments, scoring and costs (spec 5.3-5.4) ---

GAS = LpCosts(gas_mint=400_000, gas_burn_collect=200_000, priority_wei=10**8)
BASE_FEE = 10**9
STARTS_SCHEMA = {
    "block_number": pl.Int64,
    "ts_us": pl.Int64,
    "day": pl.Date,
    "tick": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "p_ref_0": pl.Float64,
    "base_fee_wei": pl.Int64,
}
SEG_COLS = ["seg", "start_block", "end_block", "center_tick", "tick_lower", "tick_upper"]


def _starts(ticks: list[int], days: list[date]) -> pl.DataFrame:
    """Block-start states for blocks 1..n, 12 s apart, at a constant reference of 2,000 USD."""
    rows = []
    for i, (t, d) in enumerate(zip(ticks, days, strict=True)):
        ts = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()) * US + 12 * US * i
        rows.append((i + 1, ts, d, t, sqrt_at(t), P0, BASE_FEE))
    return pl.DataFrame(rows, schema=STARTS_SCHEMA, orient="row")


def _unit(tick: int, lo: int, hi: int, p: float) -> tuple[float, float]:
    """(USD value, WETH) per unit of liquidity at `tick`, as pnl.time_weighted_value."""
    s, sa, sb = (1.0001 ** (x / 2) for x in (tick, lo, hi))
    s = min(max(s, sa), sb)
    eth = (s - sa) / 1e18
    return (1 / s - 1 / sb) / 1e6 + eth * p, eth


def _world_cell(
    rule: str, width: int | None, capital: float
) -> tuple[StrategyResult, CfRun, list[date]]:
    inp, run, _ = _world()
    assert run.steps is not None
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
    starts = inp.blocks_state.select("block_number", "ts_us", "tick", "sqrt_price_x96").join(
        ci.blocks.select("block_number", "day", "p_ref_0", "base_fee_wei"), on="block_number"
    )
    first, last = starts["block_number"].min(), starts["block_number"].max()
    assert isinstance(first, int) and isinstance(last, int)
    segs = segments(rule, width, starts, first, last)
    t0 = int(starts["ts_us"].min())  # type: ignore[arg-type]
    grid = hourly_grid(inp.blocks_state, t0 - t0 % HOUR_US, world_end_us())
    days = run.daily["day"].to_list()
    r = score(run.steps, segs, starts, grid, capital, GAS, TAKER_FEE_BP, days)
    return r, run, days


def test_range_ticks() -> None:
    assert range_ticks(201_003, 100) == (200_900, 201_110)
    assert range_ticks(201_000, 100) == (200_900, 201_100)
    assert range_ticks(5, None) == (-FULL, FULL)
    assert range_ticks(5, 0) == (0, 10)  # a zero width still spans one tick spacing


def test_rules() -> None:
    d1, d2 = DAY, date(2026, 7, 2)
    c = 201_003
    ticks = [c] * 5 + [c + 150] * 10  # leaves the +-100 bp range once, at block 6
    starts = _starts(ticks, [d1] * 10 + [d2] * 5)  # midnight before block 11
    got = {r: segments(r, 100, starts, 1, 15) for r in RULES}
    oor = got["out_of_range"]
    assert oor.columns == SEG_COLS
    assert oor.select("seg", "start_block", "end_block", "center_tick").rows() == [
        (0, 1, 6, c),
        (1, 6, 16, c + 150),  # the last segment ends after the period's last block
    ]
    assert oor.select("tick_lower", "tick_upper").row(1) == range_ticks(c + 150, 100)
    assert got["band"].height >= 2
    assert got["daily"]["start_block"].to_list() == [1, 11]  # the first day does not re-centre
    assert got["static"].height == 1
    assert segments("band", None, starts, 1, 15).height == 1  # full range never re-centres
    assert segments("out_of_range", 100, starts, 1, 5).height == 1  # the period ends first
    with pytest.raises(ValueError, match="block 20"):
        segments("static", 100, starts, 20, 30)


def test_value_is_carried_and_costs_charged() -> None:
    starts = _starts([T] * 4, [DAY] * 4)
    lo0, hi0, lo1, hi1 = T - 100, T + 100, T - 50, T + 150
    segs = pl.DataFrame(
        [(0, 1, 3, T, lo0, hi0), (1, 3, 5, T + 50, lo1, hi1)], schema=SEG_COLS, orient="row"
    )
    t1 = int(starts["ts_us"][0])
    grid = pl.DataFrame({"ts_us": [t1 + 3_600 * US], "sqrt": [sqrt_at(T) / 2**96], "p_cex": [P0]})
    steps = pl.DataFrame(schema=CF_STEP_SCHEMA)
    r = score(steps, segs, starts, grid, 1e6, GAS, TAKER_FEE_BP, [DAY])
    (v0, e0), (v1, e1) = _unit(T, lo0, hi0, P0), _unit(T, lo1, hi1, P0)
    ell0, ell1 = r.segs["liquidity"].to_list()
    assert math.isclose(ell0 * v0, 1e6, rel_tol=1e-9)
    assert math.isclose(ell1 * v1, ell0 * v0, rel_tol=1e-9)  # the old value, carried
    assert r.segs["eth_start"].to_list() == pytest.approx([ell0 * e0, ell1 * e1], rel=1e-9)
    day = r.daily.row(0, named=True)
    assert day["recentres"] == 1
    assert math.isclose(day["trade_usd"], abs(ell1 * e1 - ell0 * e0) * P0 * 5e-4, rel_tol=1e-9)
    gas = (GAS.gas_burn_collect + GAS.gas_mint) * (BASE_FEE + GAS.priority_wei) / 1e18 * P0
    assert math.isclose(day["gas_usd"], gas, rel_tol=1e-12)
    assert math.isclose(day["twv_usd"], 1e6, rel_tol=1e-9)
    assert (day["fee_usd"], day["lvr_usd"], day["n_blocks"], day["in_range_blocks"]) == (
        0.0,
        0.0,
        4,
        4,
    )
    assert math.isclose(r.bp_per_day, -(gas + day["trade_usd"]) / 1e6 * 1e4, rel_tol=1e-9)
    assert r.peak_ratio == 0.0


def test_capital_scaling() -> None:
    a, _, days = _world_cell("daily", 10, PRIMARY_CAPITAL)
    b, _, _ = _world_cell("daily", 10, 100_000.0)
    assert a.daily["day"].to_list() == b.daily["day"].to_list() == days
    assert a.daily["recentres"].sum() == 1
    for col in ("fee_usd", "lvr_usd", "trade_usd", "twv_usd"):
        assert a.daily[col].sum() > 0, col
        for x, y in zip(a.daily[col], b.daily[col], strict=True):
            assert math.isclose(x * 0.1, y, rel_tol=1e-9), col
    assert a.daily["gas_usd"].sum() > 0
    assert a.daily["gas_usd"].to_list() == b.daily["gas_usd"].to_list()
    assert math.isclose(a.peak_ratio * 0.1, b.peak_ratio, rel_tol=1e-9)


def test_score_full_range_equals_per_liquidity() -> None:
    r, run, _ = _world_cell("static", None, PRIMARY_CAPITAL)
    (ell,) = r.segs["liquidity"].to_list()
    per_l = run.daily.select(pl.col("fee_arb_pl") + pl.col("fee_kept_pl")).to_series()
    for got, want in zip(r.daily["fee_usd"], per_l, strict=True):
        assert math.isclose(got, ell * want, rel_tol=1e-9)
    assert r.daily["fee_usd"].sum() > 0
    assert r.daily["n_blocks"].to_list() == run.daily["n_blocks"].to_list()
    assert r.daily["in_range_blocks"].to_list() == r.daily["n_blocks"].to_list()
    assert r.daily["recentres"].sum() == 0 and r.daily["gas_usd"].sum() == 0
    assert r.peak_ratio > 0
    assert peak_share(r.peak_ratio) == r.peak_ratio / (1 + r.peak_ratio)
    assert math.isclose(peak_share(0.1, 0.5), 0.05 / 1.05)


def test_lp_costs() -> None:
    npm, other = NPM_ADDRESS, "0x" + "b2" * 20

    def e(tx: str, block: int, event: str, owner: str | None, gas: int, p: int) -> tuple[Any, ...]:
        return (tx, block, event, owner, gas, p)

    events = pl.DataFrame(
        [
            e("m1", 1, "mint", npm, 300, 12),
            e("m1", 1, "collect", npm, 300, 12),  # a second log of the same transaction
            e("m2", 2, "mint", npm, 500, 15),
            e("m3", 2, "mint", other, 9_000, 99),  # not the position manager
            e("r1", 1, "mint", npm, 7_000, 99),  # burns too, and collects nothing: neither kind
            e("r1", 1, "burn", npm, 7_000, 99),
            e("b1", 2, "burn", npm, 200, 14),
            e("b1", 2, "collect", npm, 200, 14),
            e("b2", 1, "burn", npm, 8_000, 99),  # a burn with no collect
            e("s1", 1, "swap", None, 1, 99),
        ],
        schema=["tx_hash", "block_number", "event", "owner", "receipt_gas_used"]
        + ["receipt_effective_gas_price"],
        orient="row",
    )
    blocks = pl.DataFrame({"block_number": [1, 2], "base_fee_per_gas": [10, 11]})
    # mints m1, m2; burn + collect b1; priority fees 2 (m1), 4 (m2), 3 (b1)
    assert lp_costs(events, blocks) == LpCosts(gas_mint=400, gas_burn_collect=200, priority_wei=3)
    with pytest.raises(ValueError, match="mint"):
        lp_costs(events.filter(pl.col("event") != "mint"), blocks)
