import polars as pl
import pytest

from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at


def book_at(tick: int) -> TickBook:
    return TickBook(tick=tick, sqrt_price_x96=sqrt_at(tick), liquidity=0)


def test_mint_in_range_adds_active_liquidity_out_of_range_does_not() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 1000)
    b.apply_mint(200, 300, 500)
    assert b.active_liquidity() == 1000
    assert b.liquidity_net == {-100: 1000, 100: -1000, 200: 500, 300: -500}
    assert b.initialized_ticks() == [-100, 100, 200, 300]


def test_mint_exactly_at_tick_lower_is_active_at_tick_upper_is_not() -> None:
    b = book_at(-100)
    b.apply_mint(-100, 100, 7)
    b.apply_mint(-300, -100, 5)
    assert b.active_liquidity() == 7


def test_burn_reverses_mint_and_deinitializes_ticks() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 1000)
    b.apply_burn(-100, 100, 1000)
    assert b.active_liquidity() == 0
    assert b.initialized_ticks() == []
    assert b.liquidity_net == {} and b.liquidity_gross == {}


def test_burn_more_than_minted_raises() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 10)
    with pytest.raises(ValueError):
        b.apply_burn(-100, 100, 11)


def test_burn_is_atomic_when_upper_tick_would_go_negative() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 10)
    b.apply_mint(100, 200, 5)
    before = (
        dict(b.liquidity_gross),
        dict(b.liquidity_net),
        b.initialized_ticks(),
        b.active_liquidity(),
    )
    with pytest.raises(ValueError):
        b.apply_burn(100, 200, 6)  # lower tick 100 has 15 gross, upper tick 200 only 5
    after = (
        dict(b.liquidity_gross),
        dict(b.liquidity_net),
        b.initialized_ticks(),
        b.active_liquidity(),
    )
    assert after == before


def snapshot(b: TickBook) -> tuple[object, ...]:
    return (
        dict(b.liquidity_gross),
        dict(b.liquidity_net),
        b.initialized_ticks(),
        b.active_liquidity(),
    )


@pytest.mark.parametrize(("lower", "upper"), [(0, 0), (100, -100)])
def test_mint_and_burn_reject_non_ascending_range(lower: int, upper: int) -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 10)
    before = snapshot(b)
    with pytest.raises(ValueError):
        b.apply_mint(lower, upper, 5)
    with pytest.raises(ValueError):
        b.apply_burn(lower, upper, 6)
    assert snapshot(b) == before


def test_mint_and_burn_reject_negative_amount() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 10)
    before = snapshot(b)
    with pytest.raises(ValueError):
        b.apply_mint(-100, 100, -5)
    with pytest.raises(ValueError):
        b.apply_burn(-100, 100, -5)
    assert snapshot(b) == before


def test_zero_amount_burn_is_a_noop() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 10)
    b.apply_burn(-100, 100, 0)
    assert b.active_liquidity() == 10 and b.initialized_ticks() == [-100, 100]


def test_swap_crosses_multiple_ticks_up_then_down() -> None:
    b = book_at(0)
    b.apply_mint(-100, 100, 1000)
    b.apply_mint(200, 300, 500)
    b.apply_swap(sqrt_at(250), 250)  # crosses 100 (-1000) and 200 (+500)
    assert b.active_liquidity() == 500
    b.apply_swap(sqrt_at(-150), -150)  # crosses 200, 100, -100 downward
    assert b.active_liquidity() == 0
    assert b.tick == -150


def test_boundary_down_then_up() -> None:
    b = book_at(50)
    b.apply_mint(-100, 100, 1000)
    b.apply_mint(0, 100, 300)
    assert b.active_liquidity() == 1300
    b.apply_swap(sqrt_at(0), -1)  # ends exactly on tick 0 moving down: V3 reports tick -1
    assert b.active_liquidity() == 1000
    b.apply_swap(sqrt_at(0) + 1, 0)  # tiny move up re-crosses tick 0 once
    assert b.active_liquidity() == 1300


def test_from_snapshot() -> None:
    ticks = pl.DataFrame(
        {"tick": [-100, 100], "liquidity_gross": [1000, 1000], "liquidity_net": [1000, -1000]},
        schema={"tick": pl.Int64, "liquidity_gross": pl.Int128, "liquidity_net": pl.Int128},
    )
    b = TickBook.from_snapshot(ticks, {"tick": 0, "sqrt_price_x96": sqrt_at(0), "liquidity": 1000})
    assert b.active_liquidity() == 1000 and b.initialized_ticks() == [-100, 100]
