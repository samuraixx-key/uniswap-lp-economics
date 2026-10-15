"""Finding-first titles must stay true when the numbers change (a re-render after sub-project 4):
each figure checks its claim against the data and falls back to a neutral title."""

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from vizfix import fixture_frames, write_results

from uniswap_lp_economics.viz import (
    bots,
    data,
    fees_vs_lvr,
    hero,
    markouts,
    style,
    who_pays,
)
from uniswap_lp_economics.viz import discovery as viz_discovery


def texts(fn: Any, r: data.Results) -> dict[str, str]:
    with style.theme("light"):
        fig = fn(r)
        out = {t.get_gid(): t.get_text() for t in fig.texts if t.get_gid()}
        style.svg_bytes(fig)
    return out


def load(tmp_path: Path, frames: dict[str, Any]) -> data.Results:
    return data.load_results(write_results(tmp_path, frames))


def test_window_label_comes_from_the_daily_series() -> None:
    days = pl.DataFrame({"day": [date(2026, 7, 1), date(2026, 9, 30)]})
    assert data.window_label(days) == "Jul–Sep 2026"
    assert data.window_label(days.head(1)) == "Jul 2026"
    across = pl.DataFrame({"day": [date(2025, 12, 1), date(2026, 1, 31)]})
    assert data.window_label(across) == "Dec 2025–Jan 2026"


def test_claims_hold_on_the_fixture(tmp_path: Path) -> None:
    r = load(tmp_path, fixture_frames())
    assert texts(fees_vs_lvr.lvr_vs_volatility, r)["title"].startswith("Arbitrage losses grow")
    assert (
        texts(fees_vs_lvr.cumulative, r)["title"] == "Over the window, LVR pulled ahead of LP fees"
    )
    assert texts(fees_vs_lvr.measured_vs_theory, r)["title"].startswith(
        "Measured arbitrage runs above"
    )
    assert texts(bots.bots_keep, r)["title"].startswith("Arbitrage bots hand most")
    assert texts(who_pays.every_position, r)["title"] == (
        "83% of LPs lost money against rebalancing; JIT is a coin flip"
    )
    assert texts(who_pays.lifetime, r)["title"].startswith("Over their whole life, about half")
    assert texts(markouts.markouts, r)["title"].startswith("Searchers win against the pool")
    assert texts(viz_discovery.pool_follows_binance, r)["title"].startswith("The pool follows")
    assert "Jul 2026" in texts(hero.hero, r)["subtitle"]  # the fixture's window, not typed in


def test_fees_growing_faster_gives_a_neutral_title(tmp_path: Path) -> None:
    f = fixture_frames()
    d = f["daily"]
    f["daily"] = d.with_columns(lvr_0=d["fees_usd"] + d["protocol_fee_usd"], fees_usd=d["lvr_0"])
    t = texts(fees_vs_lvr.lvr_vs_volatility, load(tmp_path, f))
    assert t["title"] == "LVR and swap fees against daily volatility"


def test_fees_ahead_of_lvr_gives_a_neutral_title_and_honest_wording(tmp_path: Path) -> None:
    f = fixture_frames()
    f["daily"] = f["daily"].with_columns(lvr_0=pl.col("lvr_0") / 10)
    f["summary"]["lp"]["daily"]["total_fees_minus_lvr_usd"] = 160.0
    t = texts(fees_vs_lvr.cumulative, load(tmp_path, f))
    assert t["title"] == "Cumulative LP fees and LVR over the window"
    assert "exceeded LVR by $160" in t["subtitle"]


def test_measured_below_theory_gives_a_neutral_title(tmp_path: Path) -> None:
    f = fixture_frames()
    f["daily"] = f["daily"].with_columns(pl.col("theory_1s") * 10, pl.col("theory_arb") * 10)
    t = texts(fees_vs_lvr.measured_vs_theory, load(tmp_path, f))
    assert t["title"] == "Measured arbitrage against the LVR formula"


def test_small_builder_payments_give_a_neutral_title(tmp_path: Path) -> None:
    f = fixture_frames()
    f["summary"]["arbitrage"].update(priority_fee_usd=5.0, coinbase_usd=5.0, kept_usd=49.0)
    t = texts(bots.bots_keep, load(tmp_path, f))
    assert t["title"] == "What arbitrage bots keep after gas and builder payments"


def test_jit_that_always_wins_is_not_called_a_coin_flip(tmp_path: Path) -> None:
    f = fixture_frames()
    f["positions"] = f["positions"].with_columns(
        pl.when(pl.col("position_id") == "j2")
        .then(5.0)
        .otherwise(pl.col("pnl_rebal_usd"))
        .alias("pnl_rebal_usd")
    )
    t = texts(who_pays.every_position, load(tmp_path, f))
    assert t["title"] == "67% of LPs lost money against rebalancing"


def test_a_non_jit_interval_spanning_zero_gives_a_neutral_title(tmp_path: Path) -> None:
    f = fixture_frames()
    f["groups"] = f["groups"].with_columns(
        pl.when(pl.col("group") == "lp_vault")
        .then(0.5)
        .otherwise(pl.col("ci_hi_bp"))
        .alias("ci_hi_bp")
    )
    t = texts(who_pays.pnl_by_group, load(tmp_path, f))
    assert t["title"] == "P&L against rebalancing by LP type and range width"


def test_lifetime_title_states_the_share_when_far_from_half(tmp_path: Path) -> None:
    f = fixture_frames()
    f["summary"]["lp"]["lifetime"]["share_beat_hold"] = 0.8
    t = texts(who_pays.lifetime, load(tmp_path, f))
    assert t["title"] == "Over their whole life, 80% of LPs beat simply holding"


def test_markout_and_discovery_titles_fall_back(tmp_path: Path) -> None:
    f = fixture_frames()
    f["markouts"] = f["markouts"].with_columns(
        pl.when(pl.col("flow_label") == "searcher")
        .then(-1.0)
        .otherwise(pl.col("mean_bp"))
        .alias("mean_bp")
    )
    f["summary"]["lead_lag"]["cross_correlation"] = [
        {"lag_blocks": k, "corr": 0.3 if k == 0 else 0.0, "n": 10} for k in range(-2, 3)
    ]
    r = load(tmp_path, f)
    assert texts(markouts.markouts, r)["title"] == "Trader markouts by flow type"
    assert texts(viz_discovery.pool_follows_binance, r)["title"] == "How the pool tracks Binance"


@pytest.mark.parametrize("fn", [fees_vs_lvr.lvr_vs_volatility])
def test_equal_slopes_do_not_crash(tmp_path: Path, fn: Any) -> None:
    f = fixture_frames()
    d = f["daily"]
    f["daily"] = d.with_columns(lvr_0=d["fees_usd"] + d["protocol_fee_usd"])
    texts(fn, load(tmp_path, f))  # parallel fits: no break-even, no ZeroDivisionError
