from datetime import UTC, datetime

from uniswap_lp_economics.strategy.params import (
    ARB_CEX_FEE_BP,
    BASELINE_FEE_BP,
    CALIBRATION_TOL,
    CAPITALS_USD,
    DELTA_DIVISOR,
    FEE_LEVELS_BP,
    FULL_RANGE,
    HALF_WIDTHS_BP,
    HEDGE_DRIFT,
    HEDGE_RULES,
    HEDGE_SYMBOL,
    JULY_START_US,
    MAX_FEE_BP,
    MIN_FEE_BP,
    MOVE_K,
    PEAK_SHARE_FLAG,
    PRIMARY_CAPITAL,
    REF_OFFSETS_S,
    REPORT_END_US,
    REPORT_START_US,
    RULES,
    S1_REL_TOL,
    TAKER_FEE_BP,
    TAKER_FEE_SENSITIVITY_BP,
    TESTED_RULES,
    UNDEFINED_MAX_SHARE,
    VOL_HALF_LIFE_BLOCKS,
    VOL_K,
    bp_to_pips,
)


def test_pre_registered_values_are_pinned() -> None:
    # Spec 5.3: widths and rebalancing rules.
    assert HALF_WIDTHS_BP == (10, 25, 50, 100, 250, 500, 1000, 2500, 5000)
    assert RULES == ("static", "out_of_range", "band", "daily")
    assert TESTED_RULES == ("out_of_range", "band", "daily")
    assert FULL_RANGE == "full_range"
    # Spec 4 and 5.3: capital, and the report period.
    assert CAPITALS_USD == (1_000_000.0, 100_000.0)
    assert PRIMARY_CAPITAL == 1_000_000.0
    assert JULY_START_US == 1_782_864_000_000_000
    assert REPORT_START_US == 1_785_542_400_000_000
    assert REPORT_END_US == 1_790_812_800_000_000
    # Spec 5.3: costs of a re-centring.
    assert TAKER_FEE_BP == 5.0
    assert TAKER_FEE_SENSITIVITY_BP == (1.0, 10.0)
    assert PEAK_SHARE_FLAG == 0.05
    # Spec 6.5: fee levels and dynamic-fee grids.
    assert FEE_LEVELS_BP == (1, 2.5, 5, 7.5, 10, 15, 20, 30, 50, 100)
    assert BASELINE_FEE_BP == 5
    assert VOL_K == (1.0, 2.0, 4.0)
    assert VOL_HALF_LIFE_BLOCKS == (25, 150, 900)
    assert MOVE_K == (0.5, 1.0, 2.0, 4.0)
    assert MIN_FEE_BP == 1.0
    assert MAX_FEE_BP == 100.0
    # Spec 6.3: arbitrage reference and CEX fee.
    assert ARB_CEX_FEE_BP == 1.0
    assert REF_OFFSETS_S == (0.0, 1.0)
    # Spec 6.4 and 7: calibration, the delta test and the undefined-draw limit.
    assert CALIBRATION_TOL == 0.15
    assert DELTA_DIVISOR == 4.0
    assert UNDEFINED_MAX_SHARE == 0.025
    # Spec 8: hedge rules and symbol.
    assert HEDGE_RULES == ("never", "daily", "hourly", "drift")
    assert HEDGE_DRIFT == 0.10
    assert HEDGE_SYMBOL == "ETHUSDC"
    # Spec 5.2: relative tolerance of the S1 check.
    assert S1_REL_TOL == 1e-9


def _utc(us: int) -> datetime:
    return datetime.fromtimestamp(us / 1_000_000, UTC)


def test_period_dates_are_utc_and_july_has_31_days() -> None:
    assert _utc(JULY_START_US) == datetime(2026, 7, 1, tzinfo=UTC)
    assert _utc(REPORT_START_US) == datetime(2026, 8, 1, tzinfo=UTC)
    assert _utc(REPORT_END_US) == datetime(2026, 10, 1, tzinfo=UTC)
    assert REPORT_START_US - JULY_START_US == 31 * 86_400 * 10**6


def test_bp_to_pips() -> None:
    assert bp_to_pips(2.5) == 250
    assert bp_to_pips(5) == 500
