from datetime import UTC, datetime

import polars as pl

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


def test_reference_table_keeps_last_trade_of_a_microsecond() -> None:
    trades = pl.DataFrame({"ts_us": [5, 5, 3], "price": [1.0, 2.0, 0.5], "qty": [1.0, 1.0, 1.0]})
    ref = reference_table(trades)
    assert ref.rows() == [(3, 0.5), (5, 2.0)]


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
