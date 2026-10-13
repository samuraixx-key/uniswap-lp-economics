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
