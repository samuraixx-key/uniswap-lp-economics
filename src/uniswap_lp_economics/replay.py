"""Public event replay: drive a TickBook through pool events in (block, log_index) order.

The generators mutate the TickBook they are given and hand control back while it holds a
well-defined state. Read what you need from it before resuming the iteration.
"""

from collections.abc import Iterator
from typing import NamedTuple

import polars as pl

from uniswap_lp_economics.tickbook import TickBook


class ReplayRow(NamedTuple):
    block_number: int
    log_index: int
    event: str
    tick: int | None
    sqrt_price_x96: int | None
    liquidity: int | None
    tick_lower: int | None
    tick_upper: int | None
    amount: int | None
    fee_protocol0_new: int | None
    fee_protocol1_new: int | None
    amount0: int | None
    amount1: int | None


REPLAY_COLUMNS = list(ReplayRow._fields)
_INT128 = {"sqrt_price_x96", "liquidity", "amount", "amount0", "amount1"}


def iter_event_rows(events: pl.DataFrame) -> Iterator[ReplayRow]:
    """Rows in (block_number, log_index) order; columns missing from `events` come back as None."""
    missing = [c for c in REPLAY_COLUMNS if c not in events.columns]
    filled = events.with_columns(
        pl.lit(None, dtype=pl.Int128 if c in _INT128 else pl.Int64).alias(c) for c in missing
    )
    for r in filled.sort("block_number", "log_index").select(REPLAY_COLUMNS).iter_rows():
        yield ReplayRow(*r)


def required(row: ReplayRow, name: str) -> int:
    """The named integer field of `row`, or a ValueError saying which event lacks it."""
    value = getattr(row, name)
    if value is None:
        raise ValueError(
            f"{row.event} at block {row.block_number} log {row.log_index} has no {name}"
        )
    return int(value)


def apply_event(book: TickBook, row: ReplayRow, fee_protocol: int) -> int:
    """Apply one event to `book` in place; return the packed feeProtocol in force afterwards."""
    if row.event == "mint":
        book.apply_mint(
            required(row, "tick_lower"), required(row, "tick_upper"), required(row, "amount")
        )
    elif row.event == "burn":
        book.apply_burn(
            required(row, "tick_lower"), required(row, "tick_upper"), required(row, "amount")
        )
    elif row.event == "swap":
        book.apply_swap(required(row, "sqrt_price_x96"), required(row, "tick"))
    elif row.event == "set_fee_protocol":
        return required(row, "fee_protocol0_new") + (required(row, "fee_protocol1_new") << 4)
    return fee_protocol


def iter_swaps_with_pre_state(
    events: pl.DataFrame, book: TickBook, fee_protocol: int
) -> Iterator[ReplayRow]:
    """Yield every swap while `book` still holds the state just before that swap."""
    for row in iter_event_rows(events):
        if row.event == "swap":
            yield row
        fee_protocol = apply_event(book, row, fee_protocol)


def iter_block_starts(
    events: pl.DataFrame, book: TickBook, fee_protocol: int, first_block: int, last_block: int
) -> Iterator[int]:
    """Yield every block number in [first_block, last_block + 1] while `book` holds the pool state
    at that block's start: after all events of earlier blocks, before any of its own.

    The final yield (last_block + 1) is the state at the end of last_block. Events outside
    [first_block, last_block] raise ValueError.
    """
    rows = iter_event_rows(events)
    pending = next(rows, None)
    if pending is not None and pending.block_number < first_block:
        raise ValueError(
            f"event in block {pending.block_number} is before first_block {first_block}"
        )
    for block in range(first_block, last_block + 1):
        yield block
        while pending is not None and pending.block_number == block:
            fee_protocol = apply_event(book, pending, fee_protocol)
            pending = next(rows, None)
    if pending is not None:
        raise ValueError(f"event in block {pending.block_number} is after last_block {last_block}")
    yield last_block + 1
