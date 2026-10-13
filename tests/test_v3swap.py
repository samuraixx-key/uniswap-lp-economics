import random

import pytest

from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import Q96
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import (
    SwapCheck,
    compute_swap_step,
    get_amount0_delta,
    get_amount1_delta,
    next_initialized_tick_within_one_word,
    swap_check_ok,
    swap_exact_input,
)

L = 10**18


def test_amount_deltas_hand_vectors() -> None:
    assert get_amount1_delta(Q96, 2 * Q96, L, True) == L
    assert get_amount1_delta(2 * Q96, Q96, L, False) == L
    assert get_amount0_delta(Q96, 2 * Q96, L, True) == L // 2
    assert get_amount0_delta(2 * Q96, Q96, L, False) == L // 2


def test_swap_step_reaching_target_hand_vector() -> None:
    # 0.05% fee on 5e17 in, rounded up: ceil(5e17 * 500 / 999500) = 250125062531266.
    assert compute_swap_step(2 * Q96, Q96, L, L, 500) == (Q96, L // 2, L, 250_125_062_531_266)


def test_swap_step_partial_hand_vector() -> None:
    sqrt_next, amount_in, amount_out, fee = compute_swap_step(Q96, 2 * Q96, L, 5 * 10**17, 500)
    assert sqrt_next == 118_822_436_730_767_940_305_917_539_516
    assert (amount_in, fee) == (499_750_000_000_000_000, 250_000_000_000_000)
    assert amount_out == 333_222_203_700_616_769


def _reference_next(initialized: set[int], tick: int, lte: bool) -> tuple[int, bool]:
    """Literal port of TickBitmap.nextInitializedTickWithinOneWord over an explicit bitmap."""
    spacing = 10
    bitmap: dict[int, int] = {}
    for t in initialized:
        c = t // spacing
        bitmap[c >> 8] = bitmap.get(c >> 8, 0) | (1 << (c & 255))
    compressed = tick // spacing
    if lte:
        word, bit = compressed >> 8, compressed & 255
        masked = bitmap.get(word, 0) & ((1 << bit) - 1 + (1 << bit))
        if masked:
            return (compressed - (bit - (masked.bit_length() - 1))) * spacing, True
        return (compressed - bit) * spacing, False
    word, bit = (compressed + 1) >> 8, (compressed + 1) & 255
    masked = bitmap.get(word, 0) & ~((1 << bit) - 1)
    if masked:
        lsb = (masked & -masked).bit_length() - 1
        return (compressed + 1 + (lsb - bit)) * spacing, True
    return (compressed + 1 + (255 - bit)) * spacing, False


def test_next_initialized_tick_matches_bitmap_reference() -> None:
    rng = random.Random(7)
    ticks = sorted({rng.randrange(-600, 600) * 10 for _ in range(40)})
    book = TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0)
    for lo, hi in zip(ticks[::2], ticks[1::2], strict=False):
        book.apply_mint(lo, hi, 1)
    init = set(book.initialized_ticks())
    for _ in range(2000):
        t = rng.randrange(-7000, 7000)
        for lte in (True, False):
            assert next_initialized_tick_within_one_word(book, t, lte) == _reference_next(
                init, t, lte
            ), (t, lte)


def two_range_book() -> TickBook:
    b = TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0)
    b.apply_mint(-10, 10, L)  # active at tick 0
    b.apply_mint(10, 20, 2 * L)
    return b


def test_swap_up_crosses_tick_and_picks_up_liquidity() -> None:
    b = two_range_book()
    to_10 = get_amount1_delta(sqrt_at(0), sqrt_at(10), L, True)
    amount = to_10 + to_10 // 4  # crosses 10, stops well before 20
    r = swap_exact_input(b, zero_for_one=False, amount_in=amount)
    assert 10 <= r.tick < 20
    assert r.liquidity == 2 * L
    assert r.amount_in == amount
    expected_out = get_amount0_delta(sqrt_at(0), sqrt_at(10), L, False) + get_amount0_delta(
        sqrt_at(10), r.sqrt_price_x96, 2 * L, False
    )
    assert r.amount_out == expected_out
    assert (b.tick, b.sqrt_price_x96, b.liquidity) == (0, sqrt_at(0), L)  # book untouched


def test_swap_down_crosses_tick_and_drops_liquidity() -> None:
    b = two_range_book()
    b.apply_swap(sqrt_at(15), 15)
    assert b.liquidity == 2 * L
    to_10 = get_amount0_delta(sqrt_at(10), sqrt_at(15), 2 * L, True)
    r = swap_exact_input(b, zero_for_one=True, amount_in=to_10 + to_10 // 4)
    assert 0 <= r.tick < 10
    assert r.liquidity == L
    expected_out = get_amount1_delta(sqrt_at(10), sqrt_at(15), 2 * L, False) + get_amount1_delta(
        r.sqrt_price_x96, sqrt_at(10), L, False
    )
    assert r.amount_out == expected_out


def test_swap_stops_at_price_limit() -> None:
    b = two_range_book()
    limit = sqrt_at(5)
    r = swap_exact_input(b, False, 10**30, sqrt_price_limit_x96=limit)
    assert r.sqrt_price_x96 == limit
    assert r.amount_in == get_amount1_delta(sqrt_at(0), limit, L, True) + r.fee
    assert r.amount_in < 10**30


def test_swap_rejects_limit_on_wrong_side_and_empty_input() -> None:
    b = two_range_book()
    with pytest.raises(ValueError, match="SPL"):
        swap_exact_input(b, True, 1, sqrt_price_limit_x96=sqrt_at(5))
    with pytest.raises(ValueError, match="positive"):
        swap_exact_input(b, True, 0)


def test_swap_check_tolerance() -> None:
    assert swap_check_ok(SwapCheck(0.0, 2, 10, False))
    assert not swap_check_ok(SwapCheck(0.0, 3, 10, False))
    assert swap_check_ok(SwapCheck(0.0, 3, 10**10, False))
    assert not swap_check_ok(SwapCheck(1e-8, 0, 10, False))
    # Two raw input units' worth of output: 2 * 1e15 / 1e6 = 2e9.
    assert swap_check_ok(SwapCheck(0.0, 6 * 10**8, 10**15, False, amount_in=10**6))
    assert not swap_check_ok(SwapCheck(0.0, 3 * 10**9, 10**15, False, amount_in=10**6))
