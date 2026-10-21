from datetime import UTC, date, datetime

import polars as pl
import pytest

from uniswap_lp_economics.config import US
from uniswap_lp_economics.lp import robustness, theory


def _us(day: int, second: int = 0) -> int:
    return int(datetime(2026, 7, day, 12, 0, second, tzinfo=UTC).timestamp()) * US


END = int(datetime(2026, 7, 4, tzinfo=UTC).timestamp()) * US
T1, T2 = _us(1), _us(2)
PRIMARY = pl.DataFrame({"ts_us": [T1, T1 + US, T2], "price": [3000.0, 3010.0, 3100.0]})
REFS = dict.fromkeys(robustness.REFERENCES, PRIMARY)


def swaps(*rows: dict[str, object]) -> pl.DataFrame:
    df = pl.DataFrame(list(rows))
    return df.with_columns(
        block_timestamp=pl.from_epoch(pl.col("t0_us"), time_unit="us").dt.replace_time_zone("UTC")
    )


SWAP_1 = {  # pool receives 1 ETH (fee in WETH), pays 3,000 USDC
    "t0_us": T1,
    "amount_usdc": -3000.0,
    "amount_eth": 1.0,
    "p_cex_0": 3000.0,
    "fee_token": "WETH",
    "protocol_fee_raw": 10**15,
    "lp_fee_raw": 3 * 10**15,
}
SWAP_2 = {
    "t0_us": T2,
    "amount_usdc": 3100.0,
    "amount_eth": -1.0,
    "p_cex_0": 3100.0,
    "fee_token": "USDC",
    "protocol_fee_raw": 500_000,
    "lp_fee_raw": 1_500_000,
}
DAILY = pl.DataFrame(
    {
        "day": [date(2026, 7, 1), date(2026, 7, 2)],
        "fees_usd": [10.0, 20.0],
        "lvr_0": [30.0, 5.0],
    }
)


def cell(table: pl.DataFrame, reference: str, offset: float) -> dict[str, object]:
    rows = table.filter((pl.col("reference") == reference) & (pl.col("offset_s") == offset))
    assert rows.height == 1
    return rows.row(0, named=True)


def test_offsets_and_references() -> None:
    assert robustness.OFFSETS_S[0] == -5.0 and robustness.OFFSETS_S[-1] == 4.0
    assert len(robustness.OFFSETS_S) == 19 and 0.0 in robustness.OFFSETS_S
    assert robustness.REFERENCES[0] == "binance_last_trade"
    assert set(robustness.REFERENCE_LABELS) == set(robustness.REFERENCES)


def test_primary_zero_offset_cell_is_the_headline_and_its_interval() -> None:
    shifts = robustness.daily_shifts(swaps(SWAP_1, SWAP_2), REFS, END)
    table = robustness.robustness_table(DAILY, shifts)
    assert table.height == 3 * 19
    row = cell(table, "binance_last_trade", 0.0)
    values = (DAILY["fees_usd"] - DAILY["lvr_0"]).to_list()
    assert row["fees_minus_lvr_usd"] == pytest.approx(sum(values))
    assert row["lp_fees_usd"] == pytest.approx(30.0)
    assert row["lvr_usd"] == pytest.approx(35.0)
    assert (row["ci_lo_usd"], row["ci_hi_usd"]) == pytest.approx(theory.day_bootstrap_sum(values))
    assert row["shift_usd"] == 0 and row["shift_ci_lo_usd"] == row["shift_ci_hi_usd"] == 0


def test_shift_is_hand_computed_for_one_swap() -> None:
    shifts = robustness.daily_shifts(swaps(SWAP_1), REFS, END, offsets=(0.0, 1.0))
    table = robustness.robustness_table(DAILY, shifts)
    row = cell(table, "binance_last_trade", 1.0)
    # price 3000 -> 3010: the pool's 1 ETH gains 10, less the 0.001 ETH protocol fee's 0.01
    assert row["shift_usd"] == pytest.approx(9.99)
    assert row["fees_minus_lvr_usd"] == pytest.approx(-5.0 + 9.99)
    assert row["lp_fees_usd"] == pytest.approx(30.0 + 0.003 * 10)  # WETH LP fee repriced
    assert row["lvr_usd"] == pytest.approx(row["lp_fees_usd"] - row["fees_minus_lvr_usd"])
    assert row["n_unpriced"] == 0


def test_missing_prices_give_zero_shift_and_are_counted() -> None:
    late = {**SWAP_2, "t0_us": END - 2 * US}  # t0 + 4 s is past the window end
    shifts = robustness.daily_shifts(swaps(SWAP_1, late), REFS, END, offsets=(0.0, 4.0))
    table = robustness.robustness_table(DAILY, shifts)
    row = cell(table, "binance_last_trade", 4.0)
    assert row["n_unpriced"] == 1
    assert all(v is not None and v == v for v in row.values() if isinstance(v, float))


def test_days_line_up_when_one_frame_lacks_a_day() -> None:
    extra = DAILY.vstack(
        pl.DataFrame({"day": [date(2026, 7, 3)], "fees_usd": [1.0], "lvr_0": [0.0]})
    )
    shifts = robustness.daily_shifts(swaps(SWAP_1), REFS, END, offsets=(0.0, 1.0))
    table = robustness.robustness_table(extra, shifts)
    row = cell(table, "binance_last_trade", 1.0)
    assert row["fees_minus_lvr_usd"] == pytest.approx(-4.0 + 9.99)
    for column in ("ci_lo_usd", "ci_hi_usd", "shift_ci_lo_usd", "shift_ci_hi_usd"):
        assert table[column].is_nan().sum() == 0 and table[column].null_count() == 0


def test_crossing_offset() -> None:
    assert robustness.crossing_offset([-4, -3, -2], [0.2, -0.2, -0.5]) == pytest.approx(-3.5)
    assert robustness.crossing_offset([-1, 0], [-0.1, -0.2]) is None
    # the last crossing counts when the curve crosses twice
    assert robustness.crossing_offset([-2, -1, 0, 1], [0.1, -0.1, 0.1, -0.1]) == pytest.approx(0.5)


def test_cells_are_anchored_on_the_primary_zero_offset_cell() -> None:
    # p_cex_0 off the primary reference (3000 at t0): the primary 0 s cell still is the headline
    off = {**SWAP_1, "p_cex_0": 2990.0}
    shifts = robustness.daily_shifts(swaps(off), REFS, END, offsets=(0.0, 1.0))
    table = robustness.robustness_table(DAILY, shifts)
    assert cell(table, "binance_last_trade", 0.0)["fees_minus_lvr_usd"] == pytest.approx(-5.0)
    assert cell(table, "binance_last_trade", 0.0)["lp_fees_usd"] == pytest.approx(30.0)
    assert cell(table, "binance_last_trade", 1.0)["shift_usd"] == pytest.approx(9.99)
