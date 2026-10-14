import random

import pytest

from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import (
    Q96,
    eth_price_to_sqrt_price_x96,
    get_tick_at_sqrt_ratio,
    sqrt_price_x96_to_eth_price,
)
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import (
    ArbResult,
    SwapCheck,
    arb_to_price,
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


def arb_book(price: float = 2000.0) -> TickBook:
    sqrt = eth_price_to_sqrt_price_x96(price)
    tick = get_tick_at_sqrt_ratio(sqrt)
    b = TickBook(tick=tick, sqrt_price_x96=sqrt, liquidity=0)
    b.apply_mint((tick // 10 - 500) * 10, (tick // 10 + 500) * 10, L)
    return b


def _profit(book: TickBook, buy_eth: bool, amount_in: int, p: float, c_bp: float = 0.0) -> float:
    r = swap_exact_input(book, buy_eth, amount_in)
    c = c_bp / 1e4
    if buy_eth:
        return r.amount_out / 1e18 * p * (1 - c) - r.amount_in / 1e6
    return r.amount_out / 1e6 - r.amount_in / 1e18 * p * (1 + c)


def test_arb_on_cheap_pool_buys_eth_up_to_fee_adjusted_price() -> None:
    b = arb_book(2000.0)
    r = arb_to_price(b, 2010.0)
    assert r.direction == "buy_eth" and r.profit_usd > 0
    end = swap_exact_input(b, True, r.amount_in)
    assert sqrt_price_x96_to_eth_price(end.sqrt_price_x96) == pytest.approx(
        2010.0 * (1 - 0.0005), rel=1e-9
    )


def test_arb_on_expensive_pool_sells_eth_down_to_fee_adjusted_price() -> None:
    b = arb_book(2000.0)
    r = arb_to_price(b, 1990.0)
    assert r.direction == "sell_eth" and r.profit_usd > 0
    end = swap_exact_input(b, False, r.amount_in)
    assert sqrt_price_x96_to_eth_price(end.sqrt_price_x96) == pytest.approx(
        1990.0 / (1 - 0.0005), rel=1e-9
    )


def test_arb_amount_maximises_profit() -> None:
    b = arb_book(2000.0)
    for p, buy in ((2010.0, True), (1990.0, False)):
        r = arb_to_price(b, p)
        assert _profit(b, buy, r.amount_in, p) == pytest.approx(r.profit_usd, rel=1e-9)
        assert _profit(b, buy, int(r.amount_in * 0.9), p) < r.profit_usd
        assert _profit(b, buy, int(r.amount_in * 1.1), p) < r.profit_usd


def test_no_arb_inside_fee_band() -> None:
    assert arb_to_price(arb_book(2000.0), 2000.5) == ArbResult("none", 0, 0, 0.0)


def test_cex_fee_reduces_profit() -> None:
    b = arb_book(2000.0)
    with_fee = arb_to_price(b, 2010.0, cex_fee_bp=1.0).profit_usd
    assert 0 < with_fee < arb_to_price(b, 2010.0).profit_usd
