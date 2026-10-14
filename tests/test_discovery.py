import math
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics.discovery import build_block_series
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import eth_price_to_sqrt_price_x96, get_tick_at_sqrt_ratio

L = 10**18
US = 1_000_000
T0 = datetime(2026, 7, 1, tzinfo=UTC)


def arb_book(price: float) -> TickBook:
    sqrt = eth_price_to_sqrt_price_x96(price)
    tick = get_tick_at_sqrt_ratio(sqrt)
    b = TickBook(tick=tick, sqrt_price_x96=sqrt, liquidity=0)
    b.apply_mint((tick // 10 - 500) * 10, (tick // 10 + 500) * 10, L)
    return b


def blocks_frame(numbers: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "block_number": numbers,
            "block_timestamp": [T0 + timedelta(seconds=12 * i) for i in range(len(numbers))],
        },
        schema={"block_number": pl.Int64, "block_timestamp": pl.Datetime("us", "UTC")},
    )


def swap_events(rows: list[tuple[int, int, float]]) -> pl.DataFrame:
    """(block, log_index, post-swap price) rows as swap events."""
    data: list[dict[str, Any]] = []
    for block, idx, price in rows:
        sqrt = eth_price_to_sqrt_price_x96(price)
        data.append(
            {
                "block_number": block,
                "log_index": idx,
                "event": "swap",
                "tick": get_tick_at_sqrt_ratio(sqrt),
                "sqrt_price_x96": sqrt,
                "liquidity": L,
            }
        )
    return pl.DataFrame(
        data,
        schema={
            "block_number": pl.Int64,
            "log_index": pl.Int64,
            "event": pl.String,
            "tick": pl.Int64,
            "sqrt_price_x96": pl.Int128,
            "liquidity": pl.Int128,
        },
    )


def test_block_series_states_basis_and_available_arbitrage() -> None:
    ref = pl.DataFrame({"ts_us": [int(T0.timestamp()) * US - 1], "price": [2010.0]})
    end_us = int(T0.timestamp()) * US + 3600 * US
    s = build_block_series(
        swap_events([(101, 0, 2009.0)]),
        arb_book(2000.0),
        68,
        blocks_frame([100, 101, 102, 103]),
        ref,
        end_us,
    )
    assert s["block_number"].to_list() == [100, 101, 102, 103]
    assert s["n_swaps"].to_list() == [0, 1, 0, 0]
    assert s["pool_price"].to_list() == pytest.approx([2000.0, 2000.0, 2009.0, 2009.0], rel=1e-9)
    assert s["end_pool_price"].to_list() == pytest.approx(
        [2000.0, 2009.0, 2009.0, 2009.0], rel=1e-9
    )
    assert s["end_sqrt_price_x96"][0] == s["sqrt_price_x96"][1]
    assert s["basis_bp"][0] == pytest.approx(math.log(2000 / 2010) * 1e4, rel=1e-6)
    assert s["arb_direction"].to_list() == ["buy_eth", "buy_eth", "none", "none"]
    avail = s["available_usd"].to_list()
    assert avail[0] > 0 and avail[2] == 0.0
    assert all(a1 <= a0 for a0, a1 in zip(avail, s["available_usd_cex1bp"], strict=True))


def test_block_series_skips_blocks_missing_from_the_block_table() -> None:
    ref = pl.DataFrame({"ts_us": [int(T0.timestamp()) * US - 1], "price": [2000.0]})
    blocks = blocks_frame([100, 101, 102]).filter(pl.col("block_number") != 101)
    s = build_block_series(swap_events([]), arb_book(2000.0), 68, blocks, ref, 10**18)
    assert s["block_number"].to_list() == [100, 102]
    assert s["arb_direction"].to_list() == ["none", "none"]
