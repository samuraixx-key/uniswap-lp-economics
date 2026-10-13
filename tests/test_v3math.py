import math

import pytest

from uniswap_lp_economics.v3math import (
    eth_price_to_sqrt_price_x96,
    sqrt_price_x96_to_eth_price,
    tick_to_eth_price,
)


def test_sqrt_price_round_trip() -> None:
    for price in (500.0, 2000.0, 4321.5):
        assert sqrt_price_x96_to_eth_price(eth_price_to_sqrt_price_x96(price)) == pytest.approx(
            price, rel=1e-12
        )


def test_known_sqrt_price() -> None:
    # USDC (token0, 6 dp) / WETH (token1, 18 dp): raw price = 1e12 / eth_usd.
    # At 2000 USD/ETH the raw price is 5e8, so sqrtPriceX96 = sqrt(5e8) * 2**96.
    sqrt_price_x96 = int(math.sqrt(5e8) * 2**96)
    assert sqrt_price_x96_to_eth_price(sqrt_price_x96) == pytest.approx(2000.0, rel=1e-12)


def test_higher_tick_means_cheaper_eth() -> None:
    # token1 (WETH) per token0 (USDC) rises with tick, so USD per ETH falls.
    assert tick_to_eth_price(200_000) < tick_to_eth_price(190_000)


def test_tick_matches_sqrt_price() -> None:
    tick = 196_256
    sqrt_price_x96 = int(1.0001 ** (tick / 2) * 2**96)
    assert tick_to_eth_price(tick) == pytest.approx(
        sqrt_price_x96_to_eth_price(sqrt_price_x96), rel=1e-9
    )
