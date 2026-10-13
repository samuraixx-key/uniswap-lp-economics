import math

import pytest

from uniswap_lp_economics.v3math import (
    MAX_SQRT_RATIO,
    MAX_TICK,
    MIN_SQRT_RATIO,
    MIN_TICK,
    eth_price_to_sqrt_price_x96,
    fee_protocol_share,
    get_sqrt_ratio_at_tick,
    get_tick_at_sqrt_ratio,
    sqrt_price_x96_to_eth_price,
    swap_fee_raw,
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


Q96 = 2**96


def test_tickmath_extremes_match_v3_constants() -> None:
    assert get_sqrt_ratio_at_tick(MIN_TICK) == MIN_SQRT_RATIO
    assert get_sqrt_ratio_at_tick(MAX_TICK) == MAX_SQRT_RATIO


def test_tickmath_every_bit_matches_float() -> None:
    # Each power of two exercises one magic constant; a typo in any constant fails here.
    for k in range(20):
        for t in (2**k, -(2**k)):
            exact = get_sqrt_ratio_at_tick(t) / Q96
            assert exact == pytest.approx(1.0001 ** (t / 2), rel=1e-9), t


def test_tick_at_sqrt_ratio_inverts_exactly() -> None:
    for t in (MIN_TICK, -500_000, -196_256, -1, 0, 1, 12_345, 500_000, MAX_TICK - 1):
        s = get_sqrt_ratio_at_tick(t)
        assert get_tick_at_sqrt_ratio(s) == t
        assert get_tick_at_sqrt_ratio(get_sqrt_ratio_at_tick(t + 1) - 1) == t


def test_tick_at_sqrt_ratio_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        get_tick_at_sqrt_ratio(MIN_SQRT_RATIO - 1)
    with pytest.raises(ValueError):
        get_tick_at_sqrt_ratio(MAX_SQRT_RATIO)


def test_swap_fee_rounds_up() -> None:
    assert swap_fee_raw(2_000 * 10**6) == 10**6  # 0.05% of 2000 USDC = 1 USDC
    assert swap_fee_raw(1) == 1
    assert swap_fee_raw(0) == 0


def test_fee_protocol_share_uses_low_nibble_for_token0() -> None:
    packed = 4 | (5 << 4)
    assert fee_protocol_share(packed, zero_for_one=True) == 0.25
    assert fee_protocol_share(packed, zero_for_one=False) == 0.2
    assert fee_protocol_share(0, zero_for_one=True) == 0.0
