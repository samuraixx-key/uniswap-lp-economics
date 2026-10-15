from datetime import UTC, date, datetime

import polars as pl
import pytest

from uniswap_lp_economics.lp import figdata
from uniswap_lp_economics.v3math import Q96

US = 1_000_000


def ts(day: int, second: int) -> int:
    return int(datetime(2026, 7, day, tzinfo=UTC).timestamp()) * US + second * US


def test_episode_window_picks_the_biggest_move_on_the_worst_day() -> None:
    daily = pl.DataFrame({"day": [date(2026, 7, 1), date(2026, 7, 2)], "lvr_0": [5.0, 9.0]})
    n = 60
    prices = [2000.0] * 30 + [2000.0 + 10 * k for k in range(1, 21)] + [2200.0] * 10
    state = pl.DataFrame(
        {
            "block_number": list(range(100, 100 + n)) + [500],
            "ts_us": [ts(2, 12 * i) for i in range(n)] + [ts(1, 0)],
            "p_cex": prices + [1.0],
        }
    )
    w = figdata.episode_window(daily, state)
    assert w.height == 32
    assert w["block_number"][0] == 100 + 29 - 4  # the 20-block move starts at block 129 (i0 = 29)
    assert 500 not in w["block_number"].to_list()  # other days are ignored


def test_episode_tables_price_lvr_and_binance_seconds() -> None:
    daily = pl.DataFrame({"day": [date(2026, 7, 2)], "lvr_0": [1.0]})
    sqrt = int(Q96 * (1e12 / 2000.0) ** 0.5)  # pool price 2000 USD per ETH
    state = pl.DataFrame(
        {
            "block_number": [1, 2, 3],
            "ts_us": [ts(2, 0), ts(2, 12), ts(2, 24)],
            "p_cex": [2000.0, 2010.0, 2020.0],
            "end_sqrt_price_x96": [sqrt, sqrt, sqrt],
        },
        schema_overrides={"end_sqrt_price_x96": pl.Int128},
    )
    steps = pl.DataFrame(
        {"block_number": [2, 2, 3], "lvr_0": [3.0, 4.0, -1.0], "flow_label": ["searcher", "x", "x"]}
    )
    trades = pl.DataFrame(
        {
            "ts_us": [ts(2, 0) + 100, ts(2, 0) + 900_000, ts(2, 5), ts(2, 99)],
            "price": [1.0, 2.0, 3.0, 9.0],
        }
    )
    blocks, cex = figdata.episode_tables(daily, state, steps, trades)
    assert blocks["pool_price"][0] == pytest.approx(2000.0, rel=1e-9)
    assert blocks["lvr_0_usd"].to_list() == [0.0, 7.0, -1.0]
    assert blocks["has_searcher"].to_list() == [False, True, False]
    assert cex.rows() == [
        (ts(2, 0), 2.0),
        (ts(2, 5), 3.0),
    ]  # last trade per second; 99 s is past the end


def _jit_inputs(full: bool) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    positions = pl.DataFrame(
        {
            "position_id": ["j1", "j2", "w"],
            "lp_type": ["jit", "jit", "nft_wallet"],
            "pnl_rebal_usd": [50.0, 10.0, 999.0],
            "start_block": [7, 8, 7],
        }
    )
    flows = pl.DataFrame(
        {
            "position_id": ["j1", "j1", "j2", "j2"],
            "block_number": [7, 7, 8, 8],
            "tx_hash": ["a", "b", "c", "c"],
            "pool_log_index": [2, 5, 1, 3],
            "liquidity_delta": [10, -10, 4, -4],
        }
    )
    # j2's transaction c swaps before its add (log 0) and after its removal (log 4); j1's do not
    swaps = pl.DataFrame(
        {
            "tx_hash": ["c", "c", "a", "z"],
            "log_index": [0, 4 if full else 2, 3, 3],
            "block_number": [8, 8, 7, 8],
        }
    )
    return positions, flows, swaps


def test_select_jit_prefers_the_full_pattern_then_falls_back() -> None:
    assert figdata.select_jit_position(*_jit_inputs(full=True)) == ("j2", True)
    assert figdata.select_jit_position(*_jit_inputs(full=False)) == ("j1", False)
    positions, flows, swaps = _jit_inputs(full=True)
    no_jit = positions.filter(pl.col("lp_type") != "jit")
    assert figdata.select_jit_position(no_jit, flows, swaps) == (None, False)


def test_jit_block_table_lists_the_block_in_log_order_with_roles() -> None:
    positions, flows, swaps = _jit_inputs(full=True)
    sqrt = int(Q96 * (1e12 / 2000.0) ** 0.5)
    events = pl.DataFrame(
        {
            "block_number": [8] * 5,
            "log_index": [0, 1, 2, 3, 4],
            "event": ["swap", "mint", "swap", "burn", "swap"],
            "tx_hash": ["c", "c", "z", "c", "c"],
            "amount0": [10**9, 10**9, 2 * 10**9, -(10**9), -(10**9)],
            "amount1": [0, 10**18, 0, -(10**18), 0],
            "sqrt_price_x96": [sqrt, None, sqrt, None, sqrt],
        },
        schema_overrides={"amount0": pl.Int128, "amount1": pl.Int128, "sqrt_price_x96": pl.Int128},
    )
    # the swaps table as aligned.parquet holds it: one row per swap event of the block
    aligned = pl.DataFrame(
        {
            "tx_hash": ["c", "z", "c"],
            "log_index": [0, 2, 4],
            "block_number": [8, 8, 8],
            "notional_usd": [1.0, 2.0, 1.0],
            "markout_usd_0": [-0.5, 0.1, -0.2],
        }
    )
    steps = pl.DataFrame(
        {"block_number": [8, 8], "log_index": [2, 2], "fee_usd": [0.3, 0.1], "lvr_0": [-1.0, -0.5]}
    )
    state = pl.DataFrame(
        {"block_number": [8], "sqrt_price_x96": [sqrt]},
        schema_overrides={"sqrt_price_x96": pl.Int128},
    )
    t = figdata.jit_block_table(positions, flows, aligned, events, steps, state)
    assert t.columns == list(figdata.JIT_BLOCK_SCHEMA)
    assert t["role"].to_list() == ["operator", "jit", "other", "jit", "operator"]
    assert t["full_pattern"].unique().to_list() == [True] and t["position_id"][0] == "j2"
    served = t.row(2, named=True)
    assert served["fee_usd"] == pytest.approx(0.4) and served["lvr_0_usd"] == pytest.approx(-1.5)
    assert served["notional_usd"] == 2.0
    assert t["pool_price_after"][1] == pytest.approx(2000.0, rel=1e-9)
    empty = figdata.jit_block_table(
        positions.filter(pl.col("lp_type") != "jit"), flows, aligned, events, steps, state
    )
    assert empty.height == 0 and empty.columns == list(figdata.JIT_BLOCK_SCHEMA)
