import polars as pl
import pytest

from uniswap_lp_economics.replay import (
    ReplayRow,
    apply_event,
    iter_block_starts,
    iter_event_rows,
    iter_swaps_with_pre_state,
    required,
)
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at

SCHEMA = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "event": pl.String,
    "tick": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "liquidity": pl.Int128,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "amount": pl.Int128,
    "fee_protocol0_new": pl.Int64,
    "fee_protocol1_new": pl.Int64,
}


def ev(block: int, idx: int, event: str, **kw: int) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(SCHEMA)
    row.update(block_number=block, log_index=idx, event=event, **kw)
    return row


def events(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA)


def book() -> TickBook:
    b = TickBook(tick=50, sqrt_price_x96=sqrt_at(50), liquidity=0)
    b.apply_mint(-100, 100, 1000)
    return b


def test_iter_event_rows_sorts_and_fills_missing_columns() -> None:
    e = events(
        [
            ev(2, 0, "swap", tick=10, sqrt_price_x96=sqrt_at(10), liquidity=1000),
            ev(1, 5, "mint", tick_lower=0, tick_upper=10, amount=1),
        ]
    )
    rows = list(iter_event_rows(e))
    assert [(r.block_number, r.log_index) for r in rows] == [(1, 5), (2, 0)]
    assert rows[0].amount0 is None and rows[1].amount1 is None


def test_apply_event_returns_new_fee_protocol() -> None:
    e = events([ev(1, 0, "set_fee_protocol", fee_protocol0_new=4, fee_protocol1_new=5)])
    assert apply_event(book(), next(iter_event_rows(e)), 0) == 4 + (5 << 4)


def test_apply_event_rejects_swap_without_price() -> None:
    row = ReplayRow(1, 0, "swap", None, None, None, None, None, None, None, None, None, None)
    with pytest.raises(ValueError, match="sqrt_price_x96"):
        apply_event(book(), row, 0)
    with pytest.raises(ValueError, match="no tick"):
        required(row, "tick")


def test_swaps_are_yielded_in_pre_state() -> None:
    e = events(
        [
            ev(1, 0, "swap", tick=150, sqrt_price_x96=sqrt_at(150) + 1, liquidity=0),
            ev(1, 1, "swap", tick=60, sqrt_price_x96=sqrt_at(60) + 1, liquidity=1000),
        ]
    )
    b = book()
    seen = [(r.log_index, b.tick, b.liquidity) for r in iter_swaps_with_pre_state(e, b, 0)]
    assert seen == [(0, 50, 1000), (1, 150, 0)]
    assert (b.tick, b.liquidity) == (60, 1000)


def test_block_starts_cover_every_block_and_end_state() -> None:
    e = events(
        [
            ev(11, 0, "swap", tick=150, sqrt_price_x96=sqrt_at(150) + 1, liquidity=0),
            ev(13, 0, "mint", tick_lower=100, tick_upper=200, amount=7),
        ]
    )
    b = book()
    states = {blk: (b.tick, b.liquidity) for blk in iter_block_starts(e, b, 0, 10, 13)}
    assert states == {10: (50, 1000), 11: (50, 1000), 12: (150, 0), 13: (150, 0), 14: (150, 7)}


def test_block_starts_reject_events_outside_range() -> None:
    e = events([ev(20, 0, "mint", tick_lower=0, tick_upper=10, amount=1)])
    with pytest.raises(ValueError, match="after last_block"):
        list(iter_block_starts(e, book(), 0, 10, 13))
    with pytest.raises(ValueError, match="before first_block"):
        list(iter_block_starts(e, book(), 0, 21, 22))
