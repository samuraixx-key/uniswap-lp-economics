import math
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
import pytest

from uniswap_lp_economics.markouts import (
    add_markouts,
    day_bootstrap_ci,
    exclude_stale,
    markout_table,
    markout_tables,
)

H = (0, 12)
SCHEMA: dict[str, Any] = {
    "block_timestamp": pl.Datetime("us", "UTC"),
    "amount_usdc": pl.Float64,
    "amount_eth": pl.Float64,
    "notional_usd": pl.Float64,
    "fee_usd": pl.Float64,
    "fee_protocol_share": pl.Float64,
    "p_cex_0": pl.Float64,
    "p_cex_12": pl.Float64,
    "cex_age_s_0": pl.Float64,
    "flow_label": pl.String,
    "size_bucket": pl.String,
}


def frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    base: dict[str, Any] = {
        "block_timestamp": datetime(2026, 7, 1, tzinfo=UTC),
        "amount_usdc": 0.0,
        "amount_eth": 0.0,
        "notional_usd": 0.0,
        "fee_usd": 0.0,
        "fee_protocol_share": 0.25,
        "p_cex_0": 2010.0,
        "p_cex_12": 2010.0,
        "cex_age_s_0": 0.1,
        "flow_label": "searcher",
        "size_bucket": "1k-10k",
    }
    return pl.DataFrame([{**base, **r} for r in rows], schema=SCHEMA)


def test_markout_signs_hand_worked() -> None:
    out = add_markouts(
        frame(
            [
                # trader buys 1 ETH for 2001 USDC; Binance says 2010: trader +9
                {"amount_usdc": 2001.0, "amount_eth": -1.0, "notional_usd": 2001.0},
                # trader sells 1 ETH for 1990 USDC; Binance says 2010: trader -20
                {"amount_usdc": -1990.0, "amount_eth": 1.0, "notional_usd": 1990.0},
            ]
        ),
        H,
    )
    assert out["markout_usd_0"].to_list() == pytest.approx([9.0, -20.0])
    assert out["markout_bp_0"].to_list() == pytest.approx([9 / 2001 * 1e4, -20 / 1990 * 1e4])


def test_lp_markout_is_trader_loss_minus_protocol_fee() -> None:
    out = add_markouts(
        frame(
            [{"amount_usdc": 2001.0, "amount_eth": -1.0, "notional_usd": 2001.0, "fee_usd": 1.0}]
        ),
        H,
    )
    assert out["protocol_fee_usd"].item() == pytest.approx(0.25)
    assert out["lp_markout_usd_0"].item() == pytest.approx(-9.25)
    total = out["markout_usd_0"] + out["lp_markout_usd_0"] + out["protocol_fee_usd"]
    assert abs(total.item()) < 1e-12


def test_zero_notional_gives_null_bp() -> None:
    out = add_markouts(frame([{"amount_eth": 0.001, "notional_usd": 0.0}]), H)
    assert out["markout_usd_0"].item() == pytest.approx(-2.01)
    assert out["markout_bp_0"].item() is None


def test_missing_reference_is_null_and_excluded_per_horizon() -> None:
    df = add_markouts(
        frame(
            [
                {"amount_usdc": -1.0, "notional_usd": 1.0},
                {"amount_usdc": -1.0, "notional_usd": 1.0, "p_cex_12": None},
            ]
        ),
        H,
    )
    assert df["markout_usd_12"].to_list()[1] is None
    t = markout_table(df, [], H)
    assert dict(zip(t["horizon_s"], t["swaps"], strict=True)) == {0: 2, 12: 1}


def test_mean_bp_is_notional_weighted() -> None:
    df = add_markouts(
        frame(
            [
                {"amount_usdc": -1.0, "notional_usd": 1000.0},  # +1 USD (+10 bp)
                {"amount_usdc": 9.0, "notional_usd": 9000.0},  # -9 USD (-10 bp)
            ]
        ),
        H,
    )
    row = markout_table(df, [], (0,)).row(0, named=True)
    assert row["mean_bp"] == pytest.approx(-8.0)
    assert row["markout_usd"] == pytest.approx(-8.0)
    assert row["notional_usd"] == pytest.approx(10_000.0)


def test_day_bootstrap_ci() -> None:
    m = np.array([1.0, 2.0, 3.0, 4.0])
    n = np.array([1000.0, 1000.0, 1000.0, 1000.0])
    lo, hi = day_bootstrap_ci(m, n)
    assert lo <= 25.0 <= hi
    assert (lo, hi) == day_bootstrap_ci(m, n)  # fixed seed
    assert all(math.isnan(x) for x in day_bootstrap_ci(np.array([]), np.array([])))


def test_markout_tables_stack_every_grouping() -> None:
    df = add_markouts(frame([{"amount_usdc": -1.0, "notional_usd": 1.0}]), H)
    t = markout_tables(df, H)
    assert t.columns[0] == "grouping"
    assert set(t["grouping"]) == {"all", "flow_label", "size_bucket", "flow_label_x_size"}


def test_exclude_stale() -> None:
    df = frame([{"cex_age_s_0": 0.5}, {"cex_age_s_0": 6.0}, {"cex_age_s_0": None}])
    assert exclude_stale(df).height == 1
