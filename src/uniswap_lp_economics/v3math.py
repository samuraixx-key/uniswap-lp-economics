"""Uniswap V3 price conversions for the USDC/WETH pool.

token0 = USDC (6 decimals), token1 = WETH (18 decimals). The pool's raw price is
token1 per token0 in base units, so USD per ETH = 10**(18 - 6) / raw_price.
"""

import math

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1

Q96 = 2**96
_DECIMAL_SCALE: float = 10.0 ** (DECIMALS1 - DECIMALS0)


def sqrt_price_x96_to_eth_price(sqrt_price_x96: int) -> float:
    """USD per ETH from a pool sqrtPriceX96 value."""
    ratio = sqrt_price_x96 / Q96
    raw_price = ratio * ratio
    return _DECIMAL_SCALE / raw_price


def eth_price_to_sqrt_price_x96(eth_price: float) -> int:
    """Inverse of sqrt_price_x96_to_eth_price (rounded down to an integer)."""
    return int(math.sqrt(_DECIMAL_SCALE / eth_price) * Q96)


def tick_to_eth_price(tick: int) -> float:
    """USD per ETH at a pool tick (raw price = 1.0001**tick)."""
    return _DECIMAL_SCALE / math.pow(1.0001, tick)


MIN_TICK = -887272
MAX_TICK = 887272
MIN_SQRT_RATIO = 4295128739
MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342

# Port of Uniswap v3-core TickMath.getSqrtRatioAtTick: (bit, multiplier) pairs.
_TICK_FACTORS = (
    (0x2, 0xFFF97272373D413259A46990580E213A),
    (0x4, 0xFFF2E50F5F656932EF12357CF3C7FDCC),
    (0x8, 0xFFE5CACA7E10E4E61C3624EAA0941CD0),
    (0x10, 0xFFCB9843D60F6159C9DB58835C926644),
    (0x20, 0xFF973B41FA98C081472E6896DFB254C0),
    (0x40, 0xFF2EA16466C96A3843EC78B326B52861),
    (0x80, 0xFE5DEE046A99A2A811C461F1969C3053),
    (0x100, 0xFCBE86C7900A88AEDCFFC83B479AA3A4),
    (0x200, 0xF987A7253AC413176F2B074CF7815E54),
    (0x400, 0xF3392B0822B70005940C7A398E4B70F3),
    (0x800, 0xE7159475A2C29B7443B29C7FA6E889D9),
    (0x1000, 0xD097F3BDFD2022B8845AD8F792AA5825),
    (0x2000, 0xA9F746462D870FDF8A65DC1F90E061E5),
    (0x4000, 0x70D869A156D2A1B890BB3DF62BAF32F7),
    (0x8000, 0x31BE135F97D08FD981231505542FCFA6),
    (0x10000, 0x9AA508B5B7A84E1C677DE54F3E99BC9),
    (0x20000, 0x5D6AF8DEDB81196699C329225EE604),
    (0x40000, 0x2216E584F5FA1EA926041BEDFE98),
    (0x80000, 0x48A170391F7DC42444E8FA2),
)


def get_sqrt_ratio_at_tick(tick: int) -> int:
    """Exact sqrtPriceX96 at a tick (TickMath.getSqrtRatioAtTick)."""
    abs_tick = abs(tick)
    if abs_tick > MAX_TICK:
        raise ValueError(f"tick {tick} out of range")
    ratio = (
        0xFFFCB933BD6FAD37AA2D162D1A594001
        if abs_tick & 0x1
        else 0x100000000000000000000000000000000
    )
    for bit, factor in _TICK_FACTORS:
        if abs_tick & bit:
            ratio = (ratio * factor) >> 128
    if tick > 0:
        ratio = (2**256 - 1) // ratio
    return (ratio >> 32) + (0 if ratio % (1 << 32) == 0 else 1)


def get_tick_at_sqrt_ratio(sqrt_price_x96: int) -> int:
    """Greatest tick whose sqrt ratio is <= sqrt_price_x96 (TickMath.getTickAtSqrtRatio)."""
    if not MIN_SQRT_RATIO <= sqrt_price_x96 < MAX_SQRT_RATIO:
        raise ValueError("sqrt price out of range")
    guess = math.floor(2 * math.log(sqrt_price_x96 / Q96) / math.log(1.0001))
    t = max(MIN_TICK, min(MAX_TICK - 1, guess))
    while t < MAX_TICK and get_sqrt_ratio_at_tick(t + 1) <= sqrt_price_x96:
        t += 1
    while get_sqrt_ratio_at_tick(t) > sqrt_price_x96:
        t -= 1
    return t


def fee_protocol_share(fee_protocol: int, zero_for_one: bool) -> float:
    """Fraction of the swap fee taken by the protocol (slot0.feeProtocol packing)."""
    denominator = fee_protocol % 16 if zero_for_one else fee_protocol >> 4
    return 1 / denominator if denominator else 0.0
