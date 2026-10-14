import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import polars as pl
import pytest

from uniswap_lp_economics.discovery import (
    ar1_half_life,
    available_vs_captured,
    basis_stats,
    build_block_series,
    cross_correlation,
    episode_summary,
    find_episodes,
)
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


def series_frame(basis: list[float | None], p_cex: float = 2000.0) -> pl.DataFrame:
    n = len(basis)
    return pl.DataFrame(
        {
            "block_number": list(range(1, n + 1)),
            "block_timestamp": [T0 + timedelta(seconds=12 * i) for i in range(n)],
            "ts_us": [int(T0.timestamp()) * US + 12 * US * i for i in range(n)],
            "basis_bp": basis,
            "p_cex": [p_cex] * n,
        },
        schema={
            "block_number": pl.Int64,
            "block_timestamp": pl.Datetime("us", "UTC"),
            "ts_us": pl.Int64,
            "basis_bp": pl.Float64,
            "p_cex": pl.Float64,
        },
    )


def swaps_frame(rows: list[tuple[int, int, str, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "block_number": pl.Int64,
            "log_index": pl.Int64,
            "flow_label": pl.String,
            "pre_price_usd": pl.Float64,
            "price_usd": pl.Float64,
        },
        orient="row",
    )


SWAPS = swaps_frame(
    [
        (3, 0, "other_contract", 2010.0, 2014.0),  # moves away from 2000
        (3, 1, "uniswap_router", 2014.0, 2012.0),  # toward, a little
        (3, 2, "searcher", 2012.0, 2001.0),  # toward, the most
    ]
)


def test_basis_stats() -> None:
    st = basis_stats(series_frame([-10.0, -2.0, 0.0, 3.0, 8.0, None]))
    assert st["blocks"] == 5
    assert st["share_outside_band"] == pytest.approx(0.4)
    assert st["quantiles_bp"]["0.5"] == pytest.approx(0.0)


def test_closer_is_swap_moving_furthest_toward_cex() -> None:
    series = series_frame([0.0, 6.0, 7.0, 2.0, 0.0, 12.0, 11.0, 9.0])
    eps = find_episodes(series, SWAPS, 5.0)
    assert eps["start_block"].to_list() == [2, 6]
    assert eps["end_block"].to_list() == [3, 8]
    assert eps["n_blocks"].to_list() == [2, 3]
    assert eps["closer"].to_list() == ["searcher", "open"]
    assert eps["duration_s"][0] == pytest.approx(24.0)
    assert eps["peak_abs_bp"][0] == pytest.approx(7.0)
    assert eps["gap_weight"][0] == pytest.approx((6.0 + 7.0) * 12)


def test_episode_closed_by_binance_when_no_swap_moves_toward() -> None:
    eps = find_episodes(series_frame([0.0, 6.0, 7.0, 2.0, 0.0, 12.0, 11.0, 9.0]), SWAPS, 10.0)
    assert eps["start_block"].to_list() == [6]
    assert eps["closer"].to_list() == ["cex"]
    summary = episode_summary(eps)
    assert summary["share_episodes"].to_list() == [1.0]


def test_find_episodes_none() -> None:
    eps = find_episodes(series_frame([0.0, 1.0, 2.0]), SWAPS, 5.0)
    assert eps.height == 0
    assert "closer" in eps.columns
    assert episode_summary(eps).height == 0


def test_cross_correlation_finds_binance_lead() -> None:
    rng = np.random.default_rng(1)
    cex = np.cumsum(rng.normal(0.0, 1e-4, 400))
    pool = np.concatenate([[cex[0]], cex[:-1]])  # pool copies Binance one block later
    series = pl.DataFrame(
        {
            "block_number": np.arange(400),
            "pool_price": 2000.0 * np.exp(pool),
            "p_cex": 2000.0 * np.exp(cex),
        }
    )
    xc = cross_correlation(series)
    corr = dict(zip(xc["lag_blocks"], xc["corr"], strict=True))
    assert corr[1] > 0.99
    assert abs(corr[0]) < 0.3
    assert xc["lag_blocks"].to_list() == list(range(-5, 6))


def test_ar1_half_life() -> None:
    rng = np.random.default_rng(2)
    b = np.zeros(20_000)
    for i in range(1, len(b)):
        b[i] = 0.5 * b[i - 1] + rng.normal()
    series = pl.DataFrame(
        {
            "block_number": np.arange(len(b)),
            "ts_us": np.arange(len(b)) * 12 * US,
            "basis_bp": b,
        }
    )
    r = ar1_half_life(series)
    assert r["phi"] == pytest.approx(0.5, abs=0.02)
    assert r["half_life_blocks"] == pytest.approx(1.0, abs=0.1)
    assert r["median_block_s"] == pytest.approx(12.0)
    assert r["half_life_s"] == pytest.approx(12.0, abs=1.2)


def test_available_vs_captured_by_day() -> None:
    series = series_frame([0.0, 0.0]).with_columns(
        available_usd=pl.Series([3.0, 4.0]), available_usd_cex1bp=pl.Series([1.0, 2.0])
    )
    aligned = pl.DataFrame(
        {
            "block_timestamp": [T0, T0],
            "flow_label": ["searcher", "uniswap_router"],
            "markout_usd_0": [2.5, -1.0],
        },
        schema={
            "block_timestamp": pl.Datetime("us", "UTC"),
            "flow_label": pl.String,
            "markout_usd_0": pl.Float64,
        },
    )
    out = available_vs_captured(series, aligned)
    assert out.row(0, named=True)["available_usd"] == pytest.approx(7.0)
    assert out.row(0, named=True)["captured_usd"] == pytest.approx(2.5)
