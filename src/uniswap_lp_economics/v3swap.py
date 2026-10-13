"""Exact-integer Uniswap V3 swap simulation over a TickBook (exact input only).

Ports SqrtPriceMath, SwapMath.computeSwapStep, TickBitmap.nextInitializedTickWithinOneWord and the
pool's swap loop. Python ints are unbounded, so Solidity's uint256 overflow branches are reproduced
explicitly where they change the result. Nothing here mutates the TickBook.
"""

from dataclasses import dataclass

from uniswap_lp_economics.config import FEE_PIPS, TICK_SPACING
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import (
    MAX_SQRT_RATIO,
    MAX_TICK,
    MIN_SQRT_RATIO,
    MIN_TICK,
    Q96,
    get_sqrt_ratio_at_tick,
    get_tick_at_sqrt_ratio,
)

_U256 = 2**256
_PIPS = 1_000_000
A1_SQRT_REL_TOL = 1e-9
A1_OUT_ABS_TOL = 2
A1_OUT_REL_TOL = 1e-9
A1_OUT_INPUT_UNITS = 2


def mul_div(a: int, b: int, d: int) -> int:
    return a * b // d


def mul_div_rounding_up(a: int, b: int, d: int) -> int:
    q, r = divmod(a * b, d)
    return q + (1 if r else 0)


def div_rounding_up(a: int, b: int) -> int:
    return -(-a // b)


def get_amount0_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    """Token0 (USDC) between two sqrt prices: L * 2^96 * (b - a) / (a * b)."""
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    numerator1 = liquidity << 96
    numerator2 = sqrt_b - sqrt_a
    if round_up:
        return div_rounding_up(mul_div_rounding_up(numerator1, numerator2, sqrt_b), sqrt_a)
    return mul_div(numerator1, numerator2, sqrt_b) // sqrt_a


def get_amount1_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    """Token1 (WETH) between two sqrt prices: L * (b - a) / 2^96."""
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    if round_up:
        return mul_div_rounding_up(liquidity, sqrt_b - sqrt_a, Q96)
    return mul_div(liquidity, sqrt_b - sqrt_a, Q96)


def next_sqrt_price_from_input(
    sqrt_price: int, liquidity: int, amount_in: int, zero_for_one: bool
) -> int:
    """SqrtPriceMath.getNextSqrtPriceFromInput."""
    if liquidity <= 0:
        raise ValueError("liquidity must be positive")
    if amount_in == 0:
        return sqrt_price
    if zero_for_one:  # getNextSqrtPriceFromAmount0RoundingUp(add = true)
        numerator1 = liquidity << 96
        product = amount_in * sqrt_price
        if product < _U256 and numerator1 + product < _U256:
            return mul_div_rounding_up(numerator1, sqrt_price, numerator1 + product)
        return div_rounding_up(numerator1, numerator1 // sqrt_price + amount_in)
    return sqrt_price + (amount_in << 96) // liquidity  # getNextSqrtPriceFromAmount1RoundingDown


def compute_swap_step(
    sqrt_current: int, sqrt_target: int, liquidity: int, amount_remaining: int, fee_pips: int
) -> tuple[int, int, int, int]:
    """SwapMath.computeSwapStep for exact input: (sqrt_next, amount_in, amount_out, fee)."""
    zero_for_one = sqrt_current >= sqrt_target
    remaining_less_fee = mul_div(amount_remaining, _PIPS - fee_pips, _PIPS)
    if zero_for_one:
        amount_in = get_amount0_delta(sqrt_target, sqrt_current, liquidity, True)
    else:
        amount_in = get_amount1_delta(sqrt_current, sqrt_target, liquidity, True)
    if remaining_less_fee >= amount_in:
        sqrt_next = sqrt_target
    else:
        sqrt_next = next_sqrt_price_from_input(
            sqrt_current, liquidity, remaining_less_fee, zero_for_one
        )
    reached = sqrt_next == sqrt_target
    if zero_for_one:
        if not reached:
            amount_in = get_amount0_delta(sqrt_next, sqrt_current, liquidity, True)
        amount_out = get_amount1_delta(sqrt_next, sqrt_current, liquidity, False)
    else:
        if not reached:
            amount_in = get_amount1_delta(sqrt_current, sqrt_next, liquidity, True)
        amount_out = get_amount0_delta(sqrt_current, sqrt_next, liquidity, False)
    if reached:
        fee = mul_div_rounding_up(amount_in, fee_pips, _PIPS - fee_pips)
    else:
        fee = amount_remaining - amount_in
    return sqrt_next, amount_in, amount_out, fee


def next_initialized_tick_within_one_word(
    book: TickBook, tick: int, lte: bool, tick_spacing: int = TICK_SPACING
) -> tuple[int, bool]:
    """TickBitmap.nextInitializedTickWithinOneWord, answered from the book's initialized ticks."""
    compressed = tick // tick_spacing  # floor, as V3 does for negative ticks
    if lte:
        word_start = (compressed - (compressed & 255)) * tick_spacing
        t = book.nearest_initialized(compressed * tick_spacing, lte=True)
        if t is not None and t >= word_start:
            return t, True
        return word_start, False
    nxt = compressed + 1
    word_end = (nxt + 255 - (nxt & 255)) * tick_spacing
    t = book.nearest_initialized(nxt * tick_spacing, lte=False)
    if t is not None and t <= word_end:
        return t, True
    return word_end, False


@dataclass(frozen=True)
class SwapResult:
    amount_in: int  # input token consumed, fee included
    amount_out: int  # output token paid out (positive)
    fee: int  # input-token fee, part of amount_in
    sqrt_price_x96: int
    tick: int
    liquidity: int


def swap_exact_input(
    book: TickBook,
    zero_for_one: bool,
    amount_in: int,
    sqrt_price_limit_x96: int | None = None,
    fee_pips: int = FEE_PIPS,
    tick_spacing: int = TICK_SPACING,
) -> SwapResult:
    """UniswapV3Pool.swap for an exact input, from the book's current state (not mutated)."""
    if amount_in <= 0:
        raise ValueError(f"amount_in must be positive, got {amount_in}")
    sqrt_price, tick, liquidity = book.sqrt_price_x96, book.tick, book.liquidity
    if sqrt_price_limit_x96 is None:
        limit = MIN_SQRT_RATIO + 1 if zero_for_one else MAX_SQRT_RATIO - 1
    else:
        limit = sqrt_price_limit_x96
    if zero_for_one:
        valid = MIN_SQRT_RATIO < limit < sqrt_price
    else:
        valid = sqrt_price < limit < MAX_SQRT_RATIO
    if not valid:
        raise ValueError("sqrt_price_limit_x96 is on the wrong side of the current price (SPL)")

    remaining, out, fees = amount_in, 0, 0
    while remaining != 0 and sqrt_price != limit:
        start = sqrt_price
        tick_next, initialized = next_initialized_tick_within_one_word(
            book, tick, zero_for_one, tick_spacing
        )
        tick_next = max(MIN_TICK, min(MAX_TICK, tick_next))
        sqrt_at_next = get_sqrt_ratio_at_tick(tick_next)
        if zero_for_one:
            target = limit if sqrt_at_next < limit else sqrt_at_next
        else:
            target = limit if sqrt_at_next > limit else sqrt_at_next
        sqrt_price, step_in, step_out, step_fee = compute_swap_step(
            sqrt_price, target, liquidity, remaining, fee_pips
        )
        remaining -= step_in + step_fee
        out += step_out
        fees += step_fee
        if sqrt_price == sqrt_at_next:
            if initialized:
                net = book.liquidity_net[tick_next]
                liquidity += -net if zero_for_one else net
                if liquidity < 0:
                    raise ValueError(f"liquidity went negative crossing tick {tick_next}")
            tick = tick_next - 1 if zero_for_one else tick_next
        elif sqrt_price != start:
            tick = get_tick_at_sqrt_ratio(sqrt_price)
    return SwapResult(amount_in - remaining, out, fees, sqrt_price, tick, liquidity)


@dataclass(frozen=True)
class SwapCheck:
    sqrt_rel_err: float
    out_abs_err: int
    out_expected: int
    exact: bool
    amount_in: int = 0  # the event's input amount, used to scale the output tolerance


def check_swap_event(
    book: TickBook, amount0: int, amount1: int, sqrt_price_x96: int, fee_pips: int = FEE_PIPS
) -> SwapCheck | None:
    """Re-simulate a historical swap from `book` (its pre-swap state) with the event's input.

    Returns None when the swap has no input (neither amount is positive).
    """
    if amount0 > 0:
        zero_for_one, amount_in, out_expected = True, amount0, -amount1
    elif amount1 > 0:
        zero_for_one, amount_in, out_expected = False, amount1, -amount0
    else:
        return None
    r = swap_exact_input(book, zero_for_one, amount_in, fee_pips=fee_pips)
    return SwapCheck(
        sqrt_rel_err=abs(r.sqrt_price_x96 - sqrt_price_x96) / sqrt_price_x96,
        out_abs_err=abs(r.amount_out - out_expected),
        out_expected=out_expected,
        exact=r.sqrt_price_x96 == sqrt_price_x96 and r.amount_out == out_expected,
        amount_in=amount_in,
    )


def swap_check_ok(c: SwapCheck) -> bool:
    """A1's tolerance (plan Ruling 2).

    Besides the absolute and relative output slack, the output may differ by two raw input units'
    worth of output. The event does not say whether the call was exact-input or exact-output, and
    an exact-output swap rounds its input up by about one raw unit (plus the fee rounding). The
    exact-input re-simulation then over-pays output by that much, which is large relative to the
    output when the input token is coarse (6-decimal USDC) and the output is fine (18-decimal WETH).
    """
    input_slack = A1_OUT_INPUT_UNITS * abs(c.out_expected) / c.amount_in if c.amount_in > 0 else 0
    out_tol = max(A1_OUT_ABS_TOL, A1_OUT_REL_TOL * abs(c.out_expected), input_slack)
    return c.sqrt_rel_err < A1_SQRT_REL_TOL and c.out_abs_err <= out_tol
