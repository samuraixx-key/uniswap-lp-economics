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


def test_flash_grows_fee_growth_like_a_swap_fee() -> None:
    s = state()
    s.fee_protocol = 4 + (4 << 4)
    records = s.flash(5, 3, 1000, 0, 2000.0, 7)
    assert len(records) == 1  # nothing paid in token1: no second record
    r = records[0]
    assert (r.step, r.zero_for_one, r.flow_label, r.liquidity) == (0, True, "flash", L)
    assert (r.amount_in, r.amount_out, r.fee) == (0, 0, 1000)
    assert (r.protocol_fee, r.lp_fee, r.crossed_tick) == (250, 750, None)
    assert (r.lvr_0, r.lvr_12, r.lvr_12_missing, r.accrued) == (0.0, 0.0, False, True)
    assert r.fee_usd == pytest.approx(750 / 1e6)
    assert s.acc.global0 == 750 * Q128 // L and s.acc.global1 == 0
    assert s.acc.fglobal[0] == pytest.approx(750 / 1e6 / L)
    assert (s.book.tick, s.book.liquidity) == (0, L)


def test_flash_in_token1_only_and_both_tokens() -> None:
    s = state()
    (r,) = s.flash(5, 3, 0, 4 * 10**15, 2000.0, 7)
    assert (r.step, r.zero_for_one, r.protocol_fee, r.lp_fee) == (1, False, 0, 4 * 10**15)
    assert r.fee_usd == pytest.approx(4 * 10**15 * 2000.0 / 1e18)
    assert s.acc.global0 == 0 and s.acc.global1 == 4 * 10**15 * Q128 // L
    both = s.flash(6, 0, 10, 20, 2000.0, 8)
    assert [x.step for x in both] == [0, 1]
    assert s.flash(7, 0, 0, 0, 2000.0, 9) == []


def test_flash_without_liquidity_accrues_nothing() -> None:
    s = PoolState(TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0), FeeAccumulators(), 0)
    (r,) = s.flash(1, 0, 1000, 0, 2000.0, 0)
    assert not r.accrued and s.acc.global0 == 0
