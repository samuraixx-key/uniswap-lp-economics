import math
from datetime import UTC, date, datetime

import polars as pl
import pytest

from uniswap_lp_economics.lp.theory import (
    GAMMA,
    LAMBDA,
    daily_theory,
    interval_theory,
    measured_daily,
    p_trade,
    regime_by_group,
    regimes,
)

US = 1_000_000


def test_p_trade_matches_the_paper() -> None:
    assert p_trade(math.sqrt(2 * LAMBDA) * GAMMA) == pytest.approx(0.5)  # eta = 1
    assert p_trade(0.0) == 0.0
    assert p_trade(1.0) == pytest.approx(1 / (1 + math.sqrt(2 * LAMBDA) * GAMMA))
    assert math.log(1.0005) == pytest.approx(GAMMA)


def test_full_range_theory_is_sigma2_over_8_times_value() -> None:
    liq, price = 10**24, 2000.0  # raw liquidity; L_dec = 1e12
    grid = pl.DataFrame({"ts_us": [0, US, 2 * US], "price": [price, price * 1.001, price]})
    state = pl.DataFrame(
        {"block_number": [1], "ts_us": [0], "liquidity": [liq], "p_cex": [price]},
        schema={
            "block_number": pl.Int64,
            "ts_us": pl.Int64,
            "liquidity": pl.Int128,
            "p_cex": pl.Float64,
        },
    )
    t = interval_theory(grid, state)
    assert t.height == 2
    r2 = float(t["r2"].sum())
    value = 2 * liq * 1e-12 * math.sqrt(price)  # full-range pool value, USD
    # Each interval uses its own start price; the second starts at price * 1.001.
    expected = sum(
        float(r) * liq * 1e-12 * math.sqrt(p) / 4
        for r, p in zip(t["r2"].to_list(), [price, price * 1.001], strict=True)
    )
    assert float(t["lvr_theory"].sum()) == pytest.approx(expected)
    assert float(t["lvr_theory"].head(1).item()) == pytest.approx(
        float(t["r2"].head(1).item()) / 8 * value
    )
    assert r2 > 0


def test_daily_theory_and_regimes() -> None:
    days = [date(2026, 7, d) for d in range(1, 10)]
    ts = [int(datetime(2026, 7, d, tzinfo=UTC).timestamp()) * US for d in range(1, 10)]
    one = pl.DataFrame(
        {
            "ts_us": ts,
            "block_number": list(range(9)),
            "r2": [1e-4 * (i + 1) for i in range(9)],
            "lvr_theory": [10.0] * 9,
        }
    )
    d = daily_theory(one, one)
    assert d["day"].to_list() == days
    row = d.row(0, named=True)
    assert row["sigma_annual"] == pytest.approx(math.sqrt(1e-4 * 365))
    assert row["theory_arb"] == pytest.approx(10.0 * row["p_trade"])
    tagged, summary = regimes(d)
    assert tagged["regime"].to_list() == ["low"] * 3 + ["mid"] * 3 + ["high"] * 3
    assert summary["regime"].to_list() == ["low", "mid", "high"]


def test_measured_daily_splits_searcher_flow() -> None:
    t = int(datetime(2026, 7, 1, tzinfo=UTC).timestamp()) * US
    steps = pl.DataFrame(
        {
            "ts_us": [t, t, t + 86400 * US],
            "flow_label": ["searcher", "x", "x"],
            "fee_usd": [1.0, 2.0, 3.0],
            "lvr_0": [4.0, -1.0, 0.5],
            "lvr_12": [4.0, -1.0, 0.5],
        }
    )
    aligned = pl.DataFrame(
        {"block_timestamp": [datetime(2026, 7, 1, tzinfo=UTC)], "protocol_fee_usd": [0.25]}
    )
    m = measured_daily(steps, aligned)
    first = m.row(0, named=True)
    assert (first["fees_usd"], first["lvr_0"], first["lvr_0_searcher"]) == (3.0, 3.0, 4.0)
    assert first["fees_searcher"] == 1.0 and first["protocol_fee_usd"] == 0.25
    assert m.row(1, named=True)["protocol_fee_usd"] == 0.0


def test_regime_by_group() -> None:
    days = pl.DataFrame(
        {
            "position_id": ["a", "a", "b"],
            "day": [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 1)],
            "fee_usd": [1.0, 2.0, 4.0],
            "lvr_0": [0.5, 0.5, 1.0],
            "lvr_12": [0.0, 0.0, 0.0],
        }
    )
    groups = pl.DataFrame({"position_id": ["a", "b"], "lp_type": ["jit", "nft_wallet"]})
    daily = pl.DataFrame({"day": [date(2026, 7, 1), date(2026, 7, 2)], "regime": ["low", "high"]})
    t = regime_by_group(days, groups, daily)
    low_jit = t.filter((pl.col("regime") == "low") & (pl.col("lp_type") == "jit")).row(
        0, named=True
    )
    assert low_jit["fees_minus_lvr_usd"] == pytest.approx(0.5)
