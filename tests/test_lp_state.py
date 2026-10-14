import pytest

from uniswap_lp_economics.lp.state import (
    Q128,
    U256,
    FeeAccumulators,
    PoolState,
    step_lvr,
)
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import get_amount1_delta, swap

L = 10**18


def state() -> PoolState:
    s = PoolState(TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0), FeeAccumulators(), 0)
    s.mint(-10, 10, L)
    return s


def test_fee_growth_follows_the_contract_floor() -> None:
    s = state()
    assert s.acc.add(True, 1000, L, (0.0, 0.0, 0.0))
    g0, g1, _ = s.inside(-10, 10)
    assert g0 == 1000 * Q128 // L and g1 == 0
    assert L * g0 // Q128 == 999  # mulDiv floors twice: the position is owed 999, not 1000


def test_crossing_flips_outside_and_keeps_inside() -> None:
    s = state()
    s.acc.add(True, 1000, L, (1.0, 2.0, 3.0))
    g = s.acc.global0
    s.book.apply_swap(sqrt_at(-11), -11)  # the price leaves the range downwards
    s.acc.cross(-10)
    assert s.acc.outside0[-10] == g
    inside0, _, floats = s.inside(-10, 10)
    assert inside0 == g and floats == pytest.approx([1.0 / L, 2.0 / L, 3.0 / L])
    s.acc.add(True, 5000, L, (1.0, 1.0, 1.0))  # fees out of range do not reach the position
    assert s.inside(-10, 10)[0] == g


def test_inside_handles_uint256_wrap() -> None:
    acc = FeeAccumulators(global0=5)
    acc.outside0[-10], acc.outside1[-10], acc.foutside[-10] = 9, 0, [0.0, 0.0, 0.0]
    acc.outside0[10], acc.outside1[10], acc.foutside[10] = 0, 0, [0.0, 0.0, 0.0]
    inside0, _, _ = acc.inside(-10, 10, 0)
    assert inside0 == (5 - 9) % U256


def test_add_with_zero_liquidity_accrues_nothing() -> None:
    s = state()
    before = (s.acc.global0, list(s.acc.fglobal))
    assert not s.acc.add(True, 1000, 0, (1.0, 1.0, 1.0))
    assert (s.acc.global0, s.acc.fglobal) == before


def test_reinitialized_tick_gets_fresh_outside_values() -> None:
    s = state()
    s.acc.add(True, 1000, L, (0.0, 0.0, 0.0))
    assert s.acc.outside0[-10] == 0  # initialized at fee growth 0 (tick -10 <= 0)
    s.burn(-10, 10, L)
    assert -10 not in s.acc.outside0  # cleared with the tick
    s.book.apply_swap(sqrt_at(-20), -20)
    s.mint(-10, 10, L)  # -10 is now above the current tick: outside starts at 0, not global
    assert s.acc.outside0[-10] == 0
    s.burn(-10, 10, L)
    s.book.apply_swap(sqrt_at(0), 0)
    s.mint(-10, 10, L)  # -10 below the current tick again: outside = global
    assert s.acc.outside0[-10] == s.acc.global0


def test_step_lvr_sign() -> None:
    # The pool sells 1 ETH for 2000 USDC while Binance says 2010: the trader gained $10.
    assert step_lvr(True, 2_000 * 10**6, 10**18, 2010.0) == pytest.approx(10.0)
    assert step_lvr(False, 10**18, 2_020 * 10**6, 2010.0) == pytest.approx(10.0)


def test_pool_state_swap_accumulates_and_crosses() -> None:
    s = state()
    s.mint(10, 20, 2 * L)
    to_10 = get_amount1_delta(sqrt_at(0), sqrt_at(10), L, True)
    run = swap(s.book, False, to_10 + to_10 // 4)
    s.fee_protocol = 4 + (4 << 4)
    records = s.swap(1, 0, run, False, run.sqrt_price_x96, run.tick, 2000.0, None, "searcher", 0)
    assert len(records) == len(run.steps) == 2
    assert sum(r.lp_fee + r.protocol_fee for r in records) == run.fee
    assert all(r.protocol_fee == r.fee // 4 for r in records)
    assert records[0].crossed_tick == 10 and records[1].crossed_tick is None
    assert all(r.lvr_12_missing for r in records)
    assert (s.book.tick, s.book.liquidity) == (run.tick, 2 * L)
    # tick 10 was initialized above the price (outside = 0), so after the cross it holds the
    # token1 growth accrued below it: exactly the first step's growth.
    assert s.acc.outside1[10] == records[0].lp_fee * Q128 // L
