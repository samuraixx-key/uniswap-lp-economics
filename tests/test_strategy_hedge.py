"""The perpetual delta hedge (spec 8): position path, rule simulation, and the hedge table."""

import math
from datetime import date

import polars as pl
import pytest

from uniswap_lp_economics.config import US
from uniswap_lp_economics.strategy.hedge import hedge_table, position_path, simulate
from uniswap_lp_economics.strategy.params import HEDGE_RULES
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at

T0 = 1_785_542_400 * US  # 2026-08-01 00:00 UTC
MIN = 60 * US
ETH = 10.0
NO_FUNDING = pl.DataFrame({"ts_us": [], "rate": []}, schema={"ts_us": pl.Int64, "rate": pl.Float64})


def _perp(n: int, step: float = 1.0) -> pl.DataFrame:
    return pl.DataFrame(
        {"ts_us": [T0 + i * MIN for i in range(n)], "close": [2000 + step * i for i in range(n)]}
    )


def _path(n: int, eth: list[float] | None = None, value: float = 40_000.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_us": [T0 + i * MIN for i in range(n)],
            "eth": eth or [ETH] * n,
            "value_usd": [value] * n,
        }
    )


def test_position_path_uses_block_state_and_segment_in_force() -> None:
    lo, hi, mid, ell = -200_000, -199_000, -199_500, 1e18
    segs = pl.DataFrame(
        {
            "seg": [0],
            "start_block": [10],
            "end_block": [30],
            "center_tick": [-199_500],
            "tick_lower": [lo],
            "tick_upper": [hi],
            "liquidity": [ell],
            "eth_start": [0.0],
        }
    )
    starts = pl.DataFrame(
        {
            "block_number": [10, 20, 30],
            "ts_us": [T0 + 60 * US, T0 + 180 * US, T0 + 300 * US],
            "sqrt_price_x96": [sqrt_at(lo), sqrt_at(mid), sqrt_at(mid)],
            "p_ref_0": [2000.0, 2500.0, 2500.0],
        }
    )
    minutes = pl.DataFrame({"ts_us": [T0 - 10 * US, T0 + 90 * US, T0 + 200 * US, T0 + 310 * US]})
    out = position_path(segs, starts, minutes)
    # the first minute is before any block state, the last in the segment's end block
    assert out["ts_us"].to_list() == [T0 + 90 * US, T0 + 200 * US]
    sa, sb = 1.0001 ** (lo / 2), 1.0001 ** (hi / 2)
    assert out["eth"][0] == pytest.approx(0.0, abs=1e-6)  # at the lower tick: all USDC
    assert out["value_usd"][0] == pytest.approx(ell * (1 / sa - 1 / sb) / 1e6, rel=1e-9)
    sp = 1.0001 ** (mid / 2)  # mid-range: both tokens
    assert out["eth"][1] == pytest.approx(ell * (sp - sa) / 1e18, rel=1e-9)
    usdc = ell * (1 / sp - 1 / sb) / 1e6
    assert out["value_usd"][1] == pytest.approx(usdc + out["eth"][1] * 2500.0, rel=1e-9)


def test_never_has_no_cost() -> None:
    out = simulate(_path(121), _perp(121), NO_FUNDING, "never", 5.0)
    assert out.columns == ["day", "hedge_pnl_usd", "funding_usd", "trade_usd", "rehedges"]
    cols = pl.col("hedge_pnl_usd", "funding_usd", "trade_usd", "rehedges")
    assert out.select(cols.abs().sum()).row(0) == (0, 0, 0, 0)


def test_hourly_on_a_linear_path() -> None:
    out = simulate(_path(121), _perp(121), NO_FUNDING, "hourly", 5.0)
    assert out["hedge_pnl_usd"].sum() == pytest.approx(-ETH * 120)
    assert out["rehedges"].sum() == 2  # minutes 60 and 120, after the first
    assert out["trade_usd"].sum() == pytest.approx(ETH * 2000 * 5.0 / 1e4)  # only the first moves h


def test_funding_sign() -> None:
    perp = _perp(121, step=0.0)
    funding = pl.DataFrame({"ts_us": [T0 + 60 * MIN + 2_000], "rate": [0.0001]})
    short = simulate(_path(121), perp, funding, "hourly", 5.0)
    assert short["funding_usd"].sum() == pytest.approx(ETH * 2000 * 0.0001)  # a short is paid
    assert simulate(_path(121), perp, funding, "never", 5.0)["funding_usd"].sum() == 0
    neg = simulate(_path(121), perp, funding.with_columns(rate=-pl.col("rate")), "hourly", 5.0)
    assert neg["funding_usd"].sum() < 0


def test_drift_rule() -> None:
    eth = [ETH] * 10 + [10.5] * 10 + [15.0] * 10
    out = simulate(_path(30, eth), _perp(30, step=0.0), NO_FUNDING, "drift", 5.0)
    # 0.5 * 2000 = 1,000 is under 10% of 40,000; 5 * 2000 = 10,000 is over it
    assert out["rehedges"].sum() == 1
    assert out["trade_usd"].sum() == pytest.approx(
        15.0 * 2000 * 5.0 / 1e4
    )  # the first set + top-up


def test_daily_rule_rehedges_at_utc_midnight() -> None:
    n = 2 * 1440
    out = simulate(_path(n), _perp(n, step=0.0), NO_FUNDING, "daily", 5.0)
    assert out["rehedges"].to_list() == [0, 1]
    assert out["day"].to_list() == [date(2026, 8, 1), date(2026, 8, 2)]


def test_table_rows() -> None:
    n = 2 * 1440
    days = [date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)]  # the third has no minutes
    lp = pl.DataFrame(
        {
            "day": days,
            "fee_usd": [30.0, 20.0, 10.0],
            "lvr_usd": [10.0, 15.0, 5.0],
            "gas_usd": [1.0, 0.0, 0.0],
            "trade_usd": [2.0, 0.0, 0.0],
            "twv_usd": [40_000.0] * 3,
        }
    )
    funding = pl.DataFrame({"ts_us": [T0 + 8 * 3600 * US + 2_000], "rate": [0.0001]})
    t = hedge_table(lp, _path(n), _perp(n), funding, 40_000.0)
    assert t.columns == [
        "strategy",
        "rule",
        "taker_fee_bp",
        "bp_per_day",
        "sd_daily_usd_per_1m",
        "mean_daily_usd_per_1m",
    ]
    assert t.height == 11
    assert "unhedged" not in t["strategy"].to_list() + t["rule"].to_list()
    assert t.filter(pl.col("rule") == "never")["taker_fee_bp"].to_list() == [0.0]
    for r in HEDGE_RULES[1:]:
        assert sorted(t.filter(pl.col("rule") == r)["taker_fee_bp"].to_list()) == [1.0, 5.0, 10.0]
    b = t.filter(pl.col("strategy") == "rebalancing_benchmark").row(0, named=True)
    flows = [30 - 10 - 1 - 2, 20 - 15, 10 - 5]
    assert b["mean_daily_usd_per_1m"] == pytest.approx(sum(flows) / 3 * 25)
    assert b["bp_per_day"] == pytest.approx(sum(flows) / 120_000 * 1e4)
    assert math.isfinite(b["sd_daily_usd_per_1m"])
    # the position value is flat and the perp rises: the hedged mean falls below the unhedged one
    never = t.filter(pl.col("rule") == "never")["mean_daily_usd_per_1m"].item()
    daily = t.filter((pl.col("rule") == "daily") & (pl.col("taker_fee_bp") == 5.0))
    assert daily["mean_daily_usd_per_1m"].item() < never


def test_position_path_reads_the_state_at_the_minutes_close() -> None:
    lo, hi, mid, ell = -200_000, -199_000, -199_500, 1e18
    segs = pl.DataFrame(
        {
            "seg": [0],
            "start_block": [10],
            "end_block": [30],
            "center_tick": [mid],
            "tick_lower": [lo],
            "tick_upper": [hi],
            "liquidity": [ell],
            "eth_start": [0.0],
        }
    )
    # the pool moves from the lower tick to mid-range 30 s into the minute opening at T0 + 60 s
    starts = pl.DataFrame(
        {
            "block_number": [10, 20],
            "ts_us": [T0, T0 + 90 * US],
            "sqrt_price_x96": [sqrt_at(lo), sqrt_at(mid)],
            "p_ref_0": [2000.0, 2000.0],
        }
    )
    out = position_path(segs, starts, pl.DataFrame({"ts_us": [T0 + 15 * US, T0 + 60 * US]}))
    sa, sp = 1.0001 ** (lo / 2), 1.0001 ** (mid / 2)
    assert out["eth"][0] == pytest.approx(0.0, abs=1e-6)  # close at T0 + 75 s: still block 10
    assert out["eth"][1] == pytest.approx(ell * (sp - sa) / 1e18, rel=1e-9)  # close at T0 + 120 s


def test_funding_uses_the_hedge_held_during_the_minute() -> None:
    # eth changes at minute 60, the first minute of the hour: hourly re-sets at that minute's
    # close, so a funding row inside it is paid on the old h
    eth = [ETH] * 60 + [12.0] * 61
    funding = pl.DataFrame({"ts_us": [T0 + 60 * MIN + 2_000], "rate": [0.0001]})
    out = simulate(_path(121, eth), _perp(121, step=0.0), funding, "hourly", 5.0)
    assert out["funding_usd"].sum() == pytest.approx(ETH * 2000 * 0.0001)
