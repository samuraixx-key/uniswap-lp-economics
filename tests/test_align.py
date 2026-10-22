from datetime import UTC, datetime

import polars as pl
import pytest

from uniswap_lp_economics import align
from uniswap_lp_economics.align import (
    add_reference_prices,
    kline_reference_table,
    reference_at,
    reference_table,
    window_end_us,
)

REF = pl.DataFrame({"ts_us": [1_000_000, 2_000_000, 5_000_000], "price": [100.0, 101.0, 102.0]})
END = 10_000_000


def test_reference_at_picks_last_trade_at_or_before() -> None:
    r = reference_at(pl.Series([2_000_000, 4_500_000, 999_999, 1_000_000]), REF, END)
    assert r["price"].to_list() == [101.0, 101.0, None, 100.0]
    assert r["age_s"].to_list() == [0.0, 2.5, None, 0.0]


def test_reference_null_at_or_after_data_end() -> None:
    r = reference_at(pl.Series([9_999_999, 10_000_000, 12_000_000]), REF, END)
    assert r["price"].to_list() == [102.0, None, None]
    assert r["age_s"].to_list()[1:] == [None, None]


def test_reference_table_keeps_the_highest_trade_id_of_a_microsecond() -> None:
    trades = pl.DataFrame(
        {
            "agg_trade_id": [11, 10, 9],
            "ts_us": [5, 5, 3],
            "price": [2.0, 1.0, 0.5],
            "qty": [1.0, 1.0, 1.0],
        }
    )
    assert reference_table(trades).rows() == [(3, 0.5), (5, 2.0)]
    # Row order must not matter: the ID decides.
    assert reference_table(trades.reverse()).rows() == [(3, 0.5), (5, 2.0)]


def test_kline_reference_uses_bar_end() -> None:
    k = pl.DataFrame({"ts_us": [0, 1_000_000], "close": [10.0, 11.0]})
    ref = kline_reference_table(k)
    got = reference_at(pl.Series([999_999, 1_000_000, 2_000_000]), ref, END)["price"].to_list()
    assert got == [None, 10.0, 11.0]


def test_add_reference_prices_horizons_and_shift() -> None:
    df = pl.DataFrame(
        {"block_timestamp": [datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)]},
        schema={"block_timestamp": pl.Datetime("us", "UTC")},
    )
    out = add_reference_prices(df, REF, END, horizons=(0, 1, 4))
    assert out["t0_us"].item() == 1_000_000
    assert [out[f"p_cex_{h}"].item() for h in (0, 1, 4)] == [100.0, 101.0, 102.0]
    assert out["cex_age_s_4"].item() == 0.0
    shifted = add_reference_prices(df, REF, END, horizons=(0,), shift_s=1.0)
    assert shifted["p_cex_0"].item() == 101.0


def test_window_end() -> None:
    assert window_end_us() == int(datetime(2026, 10, 1, tzinfo=UTC).timestamp()) * 1_000_000


def test_kline_reference_for_one_minute_bars() -> None:
    k = pl.DataFrame({"ts_us": [0, 60_000_000], "close": [10.0, 11.0]})
    ref = kline_reference_table(k, bar_s=60)
    got = reference_at(pl.Series([59_999_999, 60_000_000, 125_000_000]), ref, 10**12)["price"]
    assert got.to_list() == [None, 10.0, 11.0]


TRADES = pl.DataFrame(
    {
        "agg_trade_id": [1, 2, 3, 4],
        "ts_us": [10, 20, 20, 30],
        "price": [100.0, 101.0, 99.0, 102.0],
        "qty": [1.0] * 4,
        "is_buyer_maker": [False, False, True, False],  # False: the buyer took liquidity (ask)
    }
)


def test_trade_side_mid_uses_the_latest_of_each_side() -> None:
    # ts 10: only an ask yet, dropped; ts 20: ask 101 (id 2), bid 99 (id 3); ts 30: ask 102
    assert align.trade_side_mid_table(TRADES).to_dicts() == [
        {"ts_us": 20, "price": 100.0},
        {"ts_us": 30, "price": 100.5},
    ]
    sides = align.trade_side_table(TRADES)
    assert sides.columns == ["ts_us", "ask", "bid"] and sides["ask"].to_list() == [101.0, 102.0]


def test_proxy_quality_counts_crossed_sides() -> None:
    crossed = pl.DataFrame(
        {
            "agg_trade_id": [1, 2],
            "ts_us": [10, 11],
            "price": [100.0, 99.0],
            "qty": [1.0, 1.0],
            "is_buyer_maker": [True, False],  # bid 100, then ask 99: crossed
        }
    )
    q = align.proxy_quality(pl.Series([12, 13]), crossed, end_us=1_000)
    assert q["crossed_share"] == 1.0 and q["spread_bp_p50"] < 0
    assert q["mean_abs_last_minus_mid_bp"] == pytest.approx(0.5 / 99.5 * 1e4)
    none = align.proxy_quality(pl.Series([5]), crossed, end_us=1_000)  # before both sides
    assert none["crossed_share"] is None
