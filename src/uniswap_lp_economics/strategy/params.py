"""Pre-registered parameters of the strategy experiment (spec sections 5-8).

Every value here is fixed before the July run. Later modules import from this file and nowhere
else; a change to a value must show in tests/test_strategy_params.py.
"""

from uniswap_lp_economics.config import US

# Spec 4: UTC microseconds. July is for calibration and choices; August-September is the report.
JULY_START_US = 1_782_864_000 * US  # 2026-07-01 00:00 UTC
REPORT_START_US = 1_785_542_400 * US  # 2026-08-01 00:00 UTC
REPORT_END_US = 1_790_812_800 * US  # 2026-10-01 00:00 UTC (exclusive)

# Spec 5.3: range widths (half-widths in bp) and rebalancing rules.
HALF_WIDTHS_BP: tuple[int, ...] = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000)
RULES: tuple[str, ...] = ("static", "out_of_range", "band", "daily")
TESTED_RULES = RULES[1:]  # static cells are descriptive only
FULL_RANGE = "full_range"
CAPITALS_USD: tuple[float, ...] = (1_000_000.0, 100_000.0)
PRIMARY_CAPITAL = 1_000_000.0

# Spec 5.3: taker fee on the rebalancing trade, and its sensitivities.
TAKER_FEE_BP = 5.0
TAKER_FEE_SENSITIVITY_BP: tuple[float, ...] = (1.0, 10.0)
PEAK_SHARE_FLAG = 0.05  # spec 5.4: flag a position above this share of pool liquidity

# Spec 6.5: fixed-fee levels and the baseline fee that every comparison is paired against.
FEE_LEVELS_BP: tuple[float, ...] = (1, 2.5, 5, 7.5, 10, 15, 20, 30, 50, 100)
BASELINE_FEE_BP = 5

# Spec 6.5: dynamic-fee grids. Volatility fee = k x EWMA sigma; move fee = 5 bp + k x |last move|.
VOL_K: tuple[float, ...] = (1.0, 2.0, 4.0)
VOL_HALF_LIFE_BLOCKS: tuple[int, ...] = (25, 150, 900)  # about 5 min, 30 min, 3 h
MOVE_K: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0)
MIN_FEE_BP = 1.0  # clamp for every dynamic rule
MAX_FEE_BP = 100.0

# Spec 6.3: arbitrage reference (primary offset and sensitivity) and the CEX fee.
ARB_CEX_FEE_BP = 1.0
REF_OFFSETS_S: tuple[float, ...] = (0.0, 1.0)

# Spec 6.4 calibration tolerance; spec 7 margin delta = (1 - r0) / DELTA_DIVISOR; spec 7.1 cap on
# undefined draws.
CALIBRATION_TOL = 0.15
DELTA_DIVISOR = 4.0
UNDEFINED_MAX_SHARE = 0.025

# Spec 8: hedge rules, drift trigger, and the perpetual used for the hedge.
HEDGE_RULES: tuple[str, ...] = ("never", "daily", "hourly", "drift")
HEDGE_DRIFT = 0.10
HEDGE_SYMBOL = "ETHUSDC"  # on data.binance.vision for 2026-07..09, checked 2026-10-22

# Spec 5.2: relative tolerance of the S1 check against the engine's accumulators.
S1_REL_TOL = 1e-9


def bp_to_pips(bp: float) -> int:
    """Basis points as Uniswap fee pips (1 bp = 100 pips)."""
    return round(bp * 100)
