"""A small results/ directory with every file the figures read (chart redesign spec section 3)."""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

US = 1_000_000
T0 = 1_787_000_000 * US


def fixture_frames() -> dict[str, Any]:
    days = [date(2026, 7, 1) + timedelta(days=i) for i in range(6)]
    sigma = [0.2, 0.3, 0.4, 0.5, 0.7, 1.0]
    daily = pl.DataFrame(
        {
            "day": days,
            "fees_usd": [10.0, 14.0, 18.0, 22.0, 30.0, 45.0],
            "protocol_fee_usd": [3.0, 4.0, 6.0, 7.0, 10.0, 15.0],
            "lvr_0": [8.0, 14.0, 22.0, 30.0, 50.0, 95.0],
            "lvr_12": [9.0, 15.0, 24.0, 33.0, 55.0, 99.0],
            "lvr_0_searcher": [9.0, 16.0, 25.0, 34.0, 55.0, 100.0],
            "fees_searcher": [5.0, 7.0, 9.0, 11.0, 15.0, 22.0],
            "protocol_fees_searcher": [1.5, 2.0, 3.0, 3.5, 5.0, 7.0],
            "rv_1s": [s * s / 365 for s in sigma],
            "sigma_annual": sigma,
            "theory_1s": [7.0, 12.0, 20.0, 27.0, 45.0, 80.0],
            "theory_1m": [9.0, 15.0, 25.0, 33.0, 55.0, 100.0],
            "p_trade": [0.2, 0.25, 0.3, 0.35, 0.4, 0.5],
            "theory_arb": [1.4, 3.0, 6.0, 9.5, 18.0, 40.0],
            "theory_arb_fees": [5.6, 9.0, 14.0, 17.5, 27.0, 40.0],
            "regime": ["low", "low", "mid", "mid", "high", "high"],
        }
    )
    horizons = [0, 12, 60, 300, 3600]
    mk_rows = []
    for grouping, label, base in (
        ("all", None, 0.3),
        ("flow_label", "searcher", 3.0),
        ("flow_label", "aggregator", -6.0),
    ):
        for i, h in enumerate(horizons):
            m = base + 0.2 * i
            mk_rows.append(
                {
                    "grouping": grouping,
                    "flow_label": label,
                    "size_bucket": None,
                    "horizon_s": h,
                    "swaps": 10,
                    "notional_usd": 1e6,
                    "markout_usd": m * 100,
                    "mean_bp": m,
                    "median_bp": m,
                    "ci_lo_bp": m - 1.0,
                    "ci_hi_bp": m + 1.0,
                }
            )
    markouts = pl.DataFrame(mk_rows)
    bot_profit = pl.DataFrame(
        {
            "sender": ["0x" + "a1" * 20, "0x" + "b2" * 20, "TOTAL"],
            "gross_usd": [100.0, 60.0, 160.0],
            "kept_usd": [-10.0, 5.0, -5.0],
        }
    )
    episodes = pl.DataFrame(
        {
            "duration_s": [12.0, 24.0, 36.0, 60.0, 120.0, 12.0],
            "threshold_bp": [5.0, 5.0, 5.0, 5.0, 5.0, 10.0],
            "closer": ["searcher"] * 6,
        }
    )
    edges = [-50.0 + 0.5 * i for i in range(201)]
    basis_hist = pl.DataFrame(
        {
            "bin_lo_bp": edges[:-1],
            "bin_hi_bp": edges[1:],
            "blocks": [max(0, 50 - abs(i - 100)) for i in range(200)],
        }
    )
    positions = pl.DataFrame(
        {
            "position_id": ["j1", "j2", "w1", "w2", "v1", "dust"],
            "lp_type": ["jit", "jit", "nft_wallet", "nft_wallet", "lp_vault", "nft_wallet"],
            "twv_usd": [200_000.0, 150_000.0, 5_000.0, 80_000.0, 30_000.0, 0.5],
            "fee_usd": [10.0, 2.0, 5.0, 60.0, 12.0, 0.0],
            "lvr_0": [-6.0, 12.0, 24.0, 455.0, 70.0, 0.01],
            "gas_usd": [3.0, 3.0, 1.0, 5.0, 2.0, 0.0],
            "direct_usd": [2.0, 2.0, 0.0, 0.0, 0.0, 0.0],
            "pnl_rebal_usd": [11.0, -15.0, -20.0, -400.0, -60.0, -0.01],
        }
    )
    group_rows = []
    for grouping, group, v, lo, hi in (
        ("lp_type", "jit", 900.0, -500.0, 2500.0),
        ("lp_type", "nft_wallet", -1.3, -1.8, -1.1),
        ("lp_type", "lp_vault", -1.6, -3.0, -1.2),
        ("width_bucket", "<50", -6.0, -20.0, 3.0),
        ("width_bucket", ">=5000", -0.7, -0.8, -0.6),
    ):
        group_rows.append(
            {
                "grouping": grouping,
                "group": group,
                "positions": 2,
                "fees_usd": 1.0,
                "lvr_0_usd": 1.0,
                "gas_usd": 0.1,
                "direct_usd": 0.0,
                "pnl_rebal_usd": -1.0,
                "pnl_hold_usd": -2.0,
                "share_beat_hold": 0.4,
                "bp_per_day": v,
                "ci_lo_bp": lo,
                "ci_hi_bp": hi,
                "bp_per_day_hold": v,
            }
        )
    groups = pl.DataFrame(group_rows)
    episode_blocks = pl.DataFrame(
        {
            "block_number": [10, 11, 12, 13, 14],
            "ts_us": [T0 + 12 * US * i for i in range(5)],
            "pool_price": [2000.0, 2000.0, 2010.0, 2018.0, 2020.0],
            "p_cex": [2000.0, 2008.0, 2016.0, 2020.0, 2021.0],
            "lvr_0_usd": [0.0, 0.0, 300.0, 250.0, 40.0],
            "has_searcher": [False, False, True, True, True],
        }
    )
    episode_cex = pl.DataFrame(
        {
            "ts_us": [T0 + US * s for s in range(60)],
            "price": [2000.0 + 21.0 * min(s, 40) / 40 for s in range(60)],
        }
    )
    jit_block = pl.DataFrame(
        {
            "block_number": [12] * 5,
            "log_index": [0, 1, 2, 3, 4],
            "event": ["swap", "mint", "swap", "burn", "swap"],
            "role": ["operator", "jit", "other", "jit", "operator"],
            "tx_hash": ["c", "c", "z", "c", "c"],
            "amount_usdc": [1000.0, 50_000.0, 20_000.0, -50_000.0, -1000.0],
            "amount_eth": [0.0, 25.0, 0.0, -25.0, 0.0],
            "pool_price_before": [1990.0, 2001.0, 2001.0, 2004.0, 2004.0],
            "pool_price_after": [2001.0, 2001.0, 2004.0, 2004.0, 2002.0],
            "notional_usd": [1000.0, None, 20_000.0, None, 1000.0],
            "markout_usd_0": [-2.0, None, -8.0, None, -1.0],
            "fee_usd": [None, None, 10.0, None, None],
            "lvr_0_usd": [None, None, -6.0, None, None],
            "position_id": ["j1"] * 5,
            "full_pattern": [True] * 5,
        }
    )
    summary = {
        "lead_lag": {
            "cross_correlation": [
                {"lag_blocks": k, "corr": c, "n": 100}
                for k, c in zip(range(-3, 4), [0.0, 0.01, 0.05, 0.2, 0.35, 0.1, 0.02], strict=True)
            ]
        },
        "arbitrage": {
            "available_usd": 100.0,
            "captured_searchers_usd": 80.0,
            "top_bot_single_pool_gross_usd": 60.0,
            "gas_burned_usd": 1.0,
            "priority_fee_usd": 30.0,
            "coinbase_usd": 35.0,
            "kept_usd": -6.0,
        },
        "lp": {
            "lp_fees_usd": 139.0,
            "protocol_fees_usd": 45.0,
            "lvr_0_usd": 219.0,
            "fees_minus_lvr_usd": -80.0,
            "daily": {
                "days": 6,
                "fees_minus_lvr_usd": -80.0,
                "fees_minus_lvr_ci_lo_usd": -110.0,
                "fees_minus_lvr_ci_hi_usd": -50.0,
                "total_fees_usd": 184.0,
                "total_fees_minus_lvr_usd": -35.0,
                "total_fees_minus_lvr_ci_lo_usd": -60.0,
                "total_fees_minus_lvr_ci_hi_usd": 5.0,
                "days_lvr_above_lp_fees": 4,
                "days_lvr_above_total_fees": 2,
            },
            "lifetime": {
                "positions": 6,
                "n_excluded_carry": 0,
                "share_beat_hold": 0.5,
                "median_return": 0.0,
            },
            "lifetime_by_life": [
                {
                    "life_bucket": "<1d",
                    "positions": 3,
                    "share_beat_hold": 0.33,
                    "median_return": 0.0,
                },
                {
                    "life_bucket": ">=180d",
                    "positions": 3,
                    "share_beat_hold": 0.67,
                    "median_return": 0.1,
                },
            ],
            "lifetime_by_width": [
                {
                    "width_bucket": "<50",
                    "positions": 3,
                    "share_beat_hold": 0.4,
                    "median_return": 0.0,
                },
                {
                    "width_bucket": ">=5000",
                    "positions": 3,
                    "share_beat_hold": 0.6,
                    "median_return": 0.01,
                },
            ],
            "destination": {
                "lvr_on_searcher_swaps_usd": 100.0,
                "fees_on_searcher_swaps_usd": 48.0,
                "protocol_fees_on_searcher_swaps_usd": 16.0,
                "multi_pool_gross_usd": 6.0,
                "gas_burned_usd": 1.0,
                "builder_margin_usd": 16.0,
                "proposer_usd": 19.0,
                "searcher_kept_usd": -6.0,
                "share_fees": 0.48,
                "sensitivity_self_built": {"proposer_usd": 15.0, "builder_margin_usd": 20.0},
            },
        },
    }
    return {
        "summary": summary,
        "markouts": markouts,
        "bot_profit": bot_profit,
        "episodes": episodes,
        "basis_hist": basis_hist,
        "daily": daily,
        "positions": positions,
        "groups": groups,
        "episode_blocks": episode_blocks,
        "episode_cex": episode_cex,
        "jit_block": jit_block,
    }


def write_results(d: Path, frames: dict[str, Any]) -> Path:
    fd = d / "figure_data"
    fd.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(frames["summary"]), encoding="utf-8")
    files = {
        "markouts.csv": frames["markouts"],
        "bot_profit.csv": frames["bot_profit"],
        "episodes.csv": frames["episodes"],
        "lvr_daily.csv": frames["daily"],
        "positions.csv": frames["positions"],
        "lp_groups.csv": frames["groups"],
        "figure_data/basis_hist.csv": frames["basis_hist"],
        "figure_data/episode_blocks.csv": frames["episode_blocks"],
        "figure_data/episode_cex.csv": frames["episode_cex"],
        "figure_data/jit_block.csv": frames["jit_block"],
    }
    for name, df in files.items():
        df.write_csv(d / name)
    return d
