"""Exact-integer Uniswap V3 swap simulation over a TickBook (exact input and exact output).

Ports SqrtPriceMath, SwapMath.computeSwapStep, TickBitmap.nextInitializedTickWithinOneWord and the
pool's swap loop. Python ints are unbounded, so Solidity's uint256 overflow branches are reproduced
explicitly where they change the result. Nothing here mutates the TickBook.
"""

from collections.abc import Callable
from dataclasses import dataclass

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1, FEE_PIPS, TICK_SPACING
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import (
    MAX_SQRT_RATIO,
    MAX_TICK,
    MIN_SQRT_RATIO,
    MIN_TICK,
    Q96,
    eth_price_to_sqrt_price_x96,
    get_sqrt_ratio_at_tick,
    get_tick_at_sqrt_ratio,
    sqrt_price_x96_to_eth_price,
)

_U256 = 2**256
_PIPS = 1_000_000
A1_SQRT_REL_TOL = 1e-9
A1_OUT_ABS_TOL = 2
A1_OUT_REL_TOL = 1e-9
A1_OUT_INPUT_UNITS = 2
_HUGE = 2**128  # more than the pool could ever pay out; the price limit stops the swap


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


def next_sqrt_price_from_output(
    sqrt_price: int, liquidity: int, amount_out: int, zero_for_one: bool
) -> int:
    """SqrtPriceMath.getNextSqrtPriceFromOutput."""
    if liquidity <= 0:
        raise ValueError("liquidity must be positive")
    if amount_out == 0:
        return sqrt_price
    if zero_for_one:  # getNextSqrtPriceFromAmount1RoundingDown(add = false)
        quotient = div_rounding_up(amount_out << 96, liquidity)
        if sqrt_price <= quotient:
            raise ValueError("output exceeds what the pool holds in this range")
        return sqrt_price - quotient
    # getNextSqrtPriceFromAmount0RoundingUp(add = false)
    numerator1 = liquidity << 96
    product = amount_out * sqrt_price
    if product >= _U256 or numerator1 <= product:
        raise ValueError("output exceeds what the pool holds in this range")
    return mul_div_rounding_up(numerator1, sqrt_price, numerator1 - product)


def compute_swap_step(
    sqrt_current: int, sqrt_target: int, liquidity: int, amount_remaining: int, fee_pips: int
) -> tuple[int, int, int, int]:
    """SwapMath.computeSwapStep: (sqrt_next, amount_in, amount_out, fee).

    `amount_remaining > 0` is an exact input, `< 0` an exact output (as in V3).
    """
    zero_for_one = sqrt_current >= sqrt_target
    exact_in = amount_remaining >= 0
    amount_in = amount_out = 0
    if exact_in:
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
    else:
        if zero_for_one:
            amount_out = get_amount1_delta(sqrt_target, sqrt_current, liquidity, False)
        else:
            amount_out = get_amount0_delta(sqrt_current, sqrt_target, liquidity, False)
        if -amount_remaining >= amount_out:
            sqrt_next = sqrt_target
        else:
            sqrt_next = next_sqrt_price_from_output(
                sqrt_current, liquidity, -amount_remaining, zero_for_one
            )
    reached = sqrt_next == sqrt_target
    if zero_for_one:
        if not (reached and exact_in):
            amount_in = get_amount0_delta(sqrt_next, sqrt_current, liquidity, True)
        if not (reached and not exact_in):
            amount_out = get_amount1_delta(sqrt_next, sqrt_current, liquidity, False)
    else:
        if not (reached and exact_in):
            amount_in = get_amount1_delta(sqrt_current, sqrt_next, liquidity, True)
        if not (reached and not exact_in):
            amount_out = get_amount0_delta(sqrt_current, sqrt_next, liquidity, False)
    if not exact_in and amount_out > -amount_remaining:  # cap at the requested output
        amount_out = -amount_remaining
    if exact_in and not reached:
        fee = amount_remaining - amount_in
    else:
        fee = mul_div_rounding_up(amount_in, fee_pips, _PIPS - fee_pips)
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


@dataclass(frozen=True)
class SwapStep:
    sqrt_start: int
    sqrt_end: int
    liquidity: int  # active liquidity during the step
    amount_in: int  # input token, fee excluded
    amount_out: int
    fee: int  # input-token fee of this step (protocol cut included)
    crossed_tick: int | None  # initialized tick crossed at the end of the step


@dataclass(frozen=True)
class SwapRun:
    amount_in: int  # input token consumed, fees included
    amount_out: int
    fee: int
    sqrt_price_x96: int
    tick: int
    liquidity: int
    steps: tuple[SwapStep, ...]


def swap(
    book: TickBook,
    zero_for_one: bool,
    amount_specified: int,
    sqrt_price_limit_x96: int | None = None,
    fee_pips: int = FEE_PIPS,
    tick_spacing: int = TICK_SPACING,
) -> SwapRun:
    """UniswapV3Pool.swap from the book's current state (not mutated).

    `amount_specified > 0` is an exact input, `< 0` an exact output, as in V3.
    """
    if amount_specified == 0:
        raise ValueError("amount_specified must be non-zero")
    exact_in = amount_specified > 0
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

    remaining = amount_specified
    total_in = total_out = fees = 0
    steps: list[SwapStep] = []
    while remaining != 0 and sqrt_price != limit:
        start, step_liquidity = sqrt_price, liquidity
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
        if exact_in:
            remaining -= step_in + step_fee
        else:
            remaining += step_out
        total_in += step_in + step_fee
        total_out += step_out
        fees += step_fee
        crossed: int | None = None
        if sqrt_price == sqrt_at_next:
            if initialized:
                net = book.liquidity_net[tick_next]
                liquidity += -net if zero_for_one else net
                if liquidity < 0:
                    raise ValueError(f"liquidity went negative crossing tick {tick_next}")
                crossed = tick_next
            tick = tick_next - 1 if zero_for_one else tick_next
        elif sqrt_price != start:
            tick = get_tick_at_sqrt_ratio(sqrt_price)
        steps.append(
            SwapStep(start, sqrt_price, step_liquidity, step_in, step_out, step_fee, crossed)
        )
    return SwapRun(total_in, total_out, fees, sqrt_price, tick, liquidity, tuple(steps))


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
    r = swap(book, zero_for_one, amount_in, sqrt_price_limit_x96, fee_pips, tick_spacing)
    return SwapResult(r.amount_in, r.amount_out, r.fee, r.sqrt_price_x96, r.tick, r.liquidity)


@dataclass(frozen=True)
class SwapCheck:
    sqrt_rel_err: float
    out_abs_err: int
    out_expected: int
    exact: bool
    amount_in: int = 0  # the event's input amount (reported by A1)
    out_per_input_unit: float = 0.0  # raw output per raw input unit at the pre-swap pool price


def check_swap_event(
    book: TickBook, amount0: int, amount1: int, sqrt_price_x96: int, fee_pips: int = FEE_PIPS
) -> SwapCheck | None:
    """Re-simulate a historical swap from `book` (its pre-swap state) with the event's input.

    Returns None when the swap has no input (neither amount is positive). The result carries the
    pre-swap pool price as `out_per_input_unit`, which values the input rounding in the tolerance.
    """
    if amount0 > 0:
        zero_for_one, amount_in, out_expected = True, amount0, -amount1
    elif amount1 > 0:
        zero_for_one, amount_in, out_expected = False, amount1, -amount0
    else:
        return None
    # Raw output per raw input unit at the pre-swap price: token1/token0 = (sqrtP / 2^96)^2 when
    # USDC goes in (zero_for_one), the inverse when WETH goes in.
    if zero_for_one:
        out_per_input_unit = (book.sqrt_price_x96 / Q96) ** 2
    else:
        out_per_input_unit = (Q96 / book.sqrt_price_x96) ** 2
    r = swap_exact_input(book, zero_for_one, amount_in, fee_pips=fee_pips)
    return SwapCheck(
        sqrt_rel_err=abs(r.sqrt_price_x96 - sqrt_price_x96) / sqrt_price_x96,
        out_abs_err=abs(r.amount_out - out_expected),
        out_expected=out_expected,
        exact=r.sqrt_price_x96 == sqrt_price_x96 and r.amount_out == out_expected,
        amount_in=amount_in,
        out_per_input_unit=out_per_input_unit,
    )


def swap_check_ok(c: SwapCheck) -> bool:
    """A1's tolerance (plan Ruling 2).

    Besides the absolute and relative output slack, the output may differ by two raw input units
    valued at the pre-swap pool price. The event does not say whether the call was exact-input or
    exact-output, and an exact-output swap rounds its input up by about one raw unit (plus the fee
    rounding). The exact-input re-simulation then over-pays output by that much, which is large
    relative to the output when the input token is coarse (6-decimal USDC) and the output is fine
    (18-decimal WETH). This covers dust exact-output swaps whose whole input is rounding, where
    |out| / amount_in would badly under-value an input unit.
    """
    input_slack = A1_OUT_INPUT_UNITS * c.out_per_input_unit
    out_tol = max(A1_OUT_ABS_TOL, A1_OUT_REL_TOL * abs(c.out_expected), input_slack)
    return c.sqrt_rel_err < A1_SQRT_REL_TOL and c.out_abs_err <= out_tol


REPRODUCTION_MODES = ("exact_input", "exact_output", "to_price")


@dataclass(frozen=True)
class Reproduction:
    mode: str  # one of REPRODUCTION_MODES, or "no_input" (then run is None)
    zero_for_one: bool
    run: SwapRun | None


def reproduce_swap(
    book: TickBook,
    amount0: int,
    amount1: int,
    sqrt_price_x96: int,
    fee_pips: int = FEE_PIPS,
    modes: tuple[str, ...] = REPRODUCTION_MODES,
) -> Reproduction | None:
    """Re-run a logged swap from `book` (its pre-swap state) in the first mode that reproduces its
    logged amounts and final price bit-exactly (spec section 5); None when no mode does.

    exact_input: the logged input as an exact input. exact_output: the logged output as an exact
    output. to_price: an unlimited exact input stopped by the logged final price as the limit
    (swaps that hit their price limit).
    """
    if amount0 > 0:
        zero_for_one, amount_in, amount_out = True, amount0, -amount1
    elif amount1 > 0:
        zero_for_one, amount_in, amount_out = False, amount1, -amount0
    else:
        if sqrt_price_x96 == book.sqrt_price_x96:
            return Reproduction("no_input", False, None)
        return None

    attempts: dict[str, Callable[[], SwapRun]] = {
        "exact_input": lambda: swap(book, zero_for_one, amount_in, fee_pips=fee_pips),
        "exact_output": lambda: swap(book, zero_for_one, -amount_out, fee_pips=fee_pips),
        "to_price": lambda: swap(book, zero_for_one, _HUGE, sqrt_price_x96, fee_pips),
    }
    for mode in modes:
        if mode == "exact_output" and amount_out <= 0:
            continue
        try:
            r = attempts[mode]()
        except ValueError:
            continue
        if (
            r.amount_in == amount_in
            and r.amount_out == amount_out
            and r.sqrt_price_x96 == sqrt_price_x96
        ):
            return Reproduction(mode, zero_for_one, r)
    return None


@dataclass(frozen=True)
class ArbResult:
    direction: str  # "buy_eth" (USDC in), "sell_eth" (WETH in) or "none"
    amount_in: int
    amount_out: int
    profit_usd: float


_NO_ARB = ArbResult("none", 0, 0, 0.0)


def arb_to_price(
    book: TickBook,
    p_cex_usd: float,
    fee_pips: int = FEE_PIPS,
    cex_fee_bp: float = 0.0,
    tick_spacing: int = TICK_SPACING,
) -> ArbResult:
    """Arbitrage the pool against a CEX price, before gas (spec 6.5, plan Ruling 1).

    The arbitrageur trades until the pool's marginal price after the swap fee equals the CEX price
    after the CEX fee: buying ETH from a cheap pool stops at P_cex*(1-f)*(1-c); selling ETH into an
    expensive pool stops at P_cex*(1+c)/(1-f). Profit is valued at the CEX price after its fee.
    """
    f = fee_pips / _PIPS
    c = cex_fee_bp / 10_000
    pool = sqrt_price_x96_to_eth_price(book.sqrt_price_x96)
    low = p_cex_usd * (1 - f) * (1 - c)
    high = p_cex_usd * (1 + c) / (1 - f)
    if pool < low:  # ETH cheap in the pool: pay USDC, receive ETH, sell it on the CEX
        limit = eth_price_to_sqrt_price_x96(low)
        if limit >= book.sqrt_price_x96:  # float rounding at the band edge
            return _NO_ARB
        r = swap_exact_input(book, True, _HUGE, limit, fee_pips, tick_spacing)
        profit = r.amount_out / 10**DECIMALS1 * p_cex_usd * (1 - c) - r.amount_in / 10**DECIMALS0
        return ArbResult("buy_eth", r.amount_in, r.amount_out, profit)
    if pool > high:  # ETH expensive in the pool: pay WETH, receive USDC, buy ETH back on the CEX
        limit = eth_price_to_sqrt_price_x96(high)
        if limit <= book.sqrt_price_x96:
            return _NO_ARB
        r = swap_exact_input(book, False, _HUGE, limit, fee_pips, tick_spacing)
        profit = r.amount_out / 10**DECIMALS0 - r.amount_in / 10**DECIMALS1 * p_cex_usd * (1 + c)
        return ArbResult("sell_eth", r.amount_in, r.amount_out, profit)
    return _NO_ARB
