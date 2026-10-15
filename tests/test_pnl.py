import math
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from uniswap_lp_economics.config import NPM_ADDRESS
from uniswap_lp_economics.lp.ledger import ACCOUNT_SCHEMA
from uniswap_lp_economics.lp.pnl import (
    PNL_COLUMNS,
    Edge,
    bootstrap_ratio,
    direct_by_position,
    gas_by_position,
    group_table,
    hold_bucket,
    jit_own_swaps,
    jit_per_swap,
    load_lp_labels,
    position_amounts,
    time_weighted_value,
    tx_receipts,
    usd,
    width_bp,
    width_bucket,
    window_pnl,
)
from uniswap_lp_economics.lp.positions import FLOW_SCHEMA, POSITION_SCHEMA
from uniswap_lp_economics.v3math import Q96
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import get_amount0_delta, get_amount1_delta

L = 10**18
US = 1_000_000
WALLET, DIRECT = "0x" + "a1" * 20, "0x" + "d1" * 20


def test_position_amounts_exact() -> None:
    lo, hi = sqrt_at(-10), sqrt_at(10)
    assert position_amounts(L, -10, 10, sqrt_at(-20)) == (get_amount0_delta(lo, hi, L, False), 0)
    assert position_amounts(L, -10, 10, sqrt_at(20)) == (0, get_amount1_delta(lo, hi, L, False))
    a0, a1 = position_amounts(L, -10, 10, sqrt_at(0))
    assert a0 == get_amount0_delta(sqrt_at(0), hi, L, False)
    assert a1 == get_amount1_delta(lo, sqrt_at(0), L, False)


def test_width_and_hold_buckets() -> None:
    assert width_bp(0, 10) == pytest.approx(10.004, rel=1e-3)
    assert [width_bucket(b) for b in (10.0, 50.0, 999.0, 1000.0, 1e9)] == [
        "<50",
        "50-200",
        "200-1000",
        "1000-5000",
        ">=5000",
    ]
    assert hold_bucket(5.0, True, False) == "same_block"
    assert hold_bucket(10 * 86400.0, False, True) == "whole_window"
    assert [hold_bucket(s, False, False) for s in (60.0, 7200.0, 3 * 86400.0, 8 * 86400.0)] == [
        "<1h",
        "1h-1d",
        "1d-7d",
        ">=7d",
    ]


def test_load_lp_labels_rejects_wrong_category(tmp_path: Path) -> None:
    p = tmp_path / "lp.csv"
    p.write_text(
        "address,name,category,source_url,notes\n"
        f"{DIRECT},Some vault,aggregator,https://example.org,\n"
    )
    with pytest.raises(ValueError, match="line 2: category"):
        load_lp_labels(p)


def pos(pid: str, kind: str, owner: str, lp: str, token: int | None = None) -> dict[str, Any]:
    return {
        "position_id": pid,
        "kind": kind,
        "token_id": token,
        "owner": owner,
        "tick_lower": -10,
        "tick_upper": 10,
        "lp": lp,
        "transferred": False,
        "first_block": 1,
        "first_ts_us": 0,
        "close_block": None,
        "close_ts_us": None,
    }


def acc(
    pid: str,
    start: int,
    end: int,
    fees: tuple[int, int],
    fee_usd: float,
    lvr: float,
    active: bool = True,
) -> dict[str, Any]:
    return {
        "position_id": pid,
        "liquidity_start": start,
        "liquidity_end": end,
        "active": active,
        "carried_owed": False,
        "owed_handed_on": False,
        "fees_raw0": fees[0],
        "fees_raw1": fees[1],
        "fee_usd": fee_usd,
        "lvr_0": lvr,
        "lvr_12": lvr / 2,
        "owed_end0": 0,
        "owed_end1": 0,
        "pending_end0": 0,
        "pending_end1": 0,
    }


def flow(pid: str, block: int, event: str, delta: int, a0: int, a1: int) -> dict[str, Any]:
    return {
        "position_id": pid,
        "kind": "nft" if pid.startswith("nft") else "direct",
        "token_id": None,
        "block_number": block,
        "log_index": 0,
        "pool_log_index": 0,
        "tx_hash": f"0x{block:064x}",
        "ts_us": block * 12 * US,
        "event": event,
        "liquidity_delta": delta,
        "amount0": a0,
        "amount1": a1,
    }


PRICES = {
    1: (12 * US, 2000.0),
    20: (240 * US, 2000.0),
    25: (300 * US, 2000.0),
    30: (360 * US, 2100.0),
    99: (1188 * US, 2050.0),
}
START = Edge(1, 12 * US, sqrt_at(0), 2000.0)
END = Edge(99, 1188 * US, sqrt_at(0), 2050.0)


def pnl_frame(has_code: dict[str, bool] | None = None) -> pl.DataFrame:
    positions = pl.DataFrame(
        [
            pos("direct:a", "direct", DIRECT, DIRECT),
            pos("nft:1", "nft", NPM_ADDRESS, WALLET, 1),
            pos("direct:j", "direct", DIRECT, DIRECT),
            pos("nft:2", "nft", NPM_ADDRESS, WALLET, 2),
        ],
        schema=POSITION_SCHEMA,
    )
    accounts = pl.DataFrame(
        [
            acc("direct:a", L, L, (100, 0), 5.0, 2.0),
            acc("nft:1", 0, 0, (50, 10**12), 1.0, 0.5),
            acc("direct:j", 0, 0, (3, 0), 0.1, 0.05),
            acc("nft:2", 0, 0, (0, 0), 0.0, 0.0, False),
        ],
        schema=ACCOUNT_SCHEMA,
    )
    flows = pl.DataFrame(
        [
            flow("nft:1", 20, "increase", L, 1000, 10**15),
            flow("nft:1", 30, "decrease", -L, 900, 2 * 10**15),
            flow("direct:j", 25, "mint", L, 10, 10),
            flow("direct:j", 25, "burn", -L, 12, 9),
            flow("nft:2", 40, "collect", 0, 1, 1),
        ],
        schema=FLOW_SCHEMA,
    )
    return window_pnl(
        positions,
        accounts,
        flows,
        PRICES,
        {"nft:1": 0.5},
        {"direct:a": 100.0, "nft:1": 50.0},
        set(),
        {WALLET: False} if has_code is None else has_code,
        START,
        END,
        direct={"nft:1": 0.25},
    )


def test_collect_only_position_is_not_window_active() -> None:
    assert "nft:2" not in pnl_frame()["position_id"].to_list()


def test_window_pnl_rows() -> None:
    df = {r["position_id"]: r for r in pnl_frame().iter_rows(named=True)}
    a, n, j = df["direct:a"], df["nft:1"], df["direct:j"]
    assert a["cohort"] == "pre_window" and a["holding"] == "whole_window"
    assert a["pnl_rebal_usd"] == pytest.approx(3.0)
    expected = usd(900 + 50 - 1000, 2 * 10**15 + 10**12 - 10**15, 2100.0) - 0.5 - 0.25
    assert n["pnl_hold_usd"] == pytest.approx(expected)
    assert n["gas_usd"] == pytest.approx(0.5) and n["direct_usd"] == pytest.approx(0.25)
    assert n["pnl_rebal_usd"] == pytest.approx(1.0 - 0.5 - 0.5 - 0.25)
    assert a["direct_usd"] == 0.0
    assert n["lp_type"] == "nft_wallet" and n["cohort"] == "in_window"
    assert n["bp_per_day"] == pytest.approx(n["pnl_rebal_usd"] / (50.0 * (360 - 240) / 86400) * 1e4)
    assert j["lp_type"] == "jit" and j["holding"] == "same_block"
    assert j["days_active"] == pytest.approx(12 / 86400)


def test_missing_owner_code_names_the_command() -> None:
    with pytest.raises(ValueError, match="ulpe fetch-chain-state"):
        pnl_frame(has_code={})


def test_time_weighted_value_on_an_hourly_grid() -> None:
    g0 = 0
    grid = pl.DataFrame(
        {
            "ts_us": [g0 + k * 3600 * US for k in range(4)],
            "sqrt": [sqrt_at(0) / Q96] * 4,
            "p_cex": [2000.0] * 4,
        }
    )
    path = pl.DataFrame(
        {"position_id": ["p", "q"], "ts_us": [0, 0], "liquidity": [L, L]},
        schema={"position_id": pl.String, "ts_us": pl.Int64, "liquidity": pl.Int128},
    )
    spans = pl.DataFrame(
        {
            "position_id": ["p", "q"],
            "tick_lower": [-10, -10],
            "tick_upper": [10, 10],
            "t_start_us": [0, 0],
            "t_exit_us": [2 * 3600 * US, 1800 * US],
        }
    )
    twv = dict(time_weighted_value(path, spans, grid).iter_rows())
    exact = usd(*position_amounts(L, -10, 10, sqrt_at(0)), 2000.0)
    assert twv["p"] == pytest.approx(exact, rel=1e-9)
    assert "q" in twv  # the grid point at t = 0 lies inside q's 30 minutes


def test_group_table_ratio_and_ci() -> None:
    pnl = pl.DataFrame(
        {
            "lp_type": ["jit", "jit", "nft_wallet"],
            "fee_usd": [1.0, 1.0, 2.0],
            "lvr_0": [0.5, 0.5, 1.0],
            "gas_usd": [0.0, 0.0, 0.0],
            "direct_usd": [0.5, 0.25, 0.0],
            "pnl_rebal_usd": [1.0, 3.0, 1.0],
            "pnl_hold_usd": [1.0, -1.0, 2.0],
            "capital_days": [100.0, 100.0, 50.0],
        }
    )
    t = group_table(pnl, "lp_type", ("jit", "lp_vault", "nft_wallet"))
    assert t["lp_type"].to_list() == ["jit", "nft_wallet"]  # empty groups are left out
    jit = t.row(0, named=True)
    assert jit["positions"] == 2 and jit["bp_per_day"] == pytest.approx(4.0 / 200.0 * 1e4)
    assert jit["share_beat_hold"] == pytest.approx(0.5)
    assert jit["direct_usd"] == pytest.approx(0.75)
    assert jit["ci_lo_bp"] <= jit["bp_per_day"] <= jit["ci_hi_bp"]


def test_gas_by_position_splits_a_transaction_across_the_positions_it_touched() -> None:
    flows = pl.DataFrame(
        [
            flow("nft:1", 20, "increase", L, 1, 1),
            flow("direct:j", 20, "mint", L, 1, 1),
            flow("nft:1", 30, "decrease", -L, 1, 1),
        ],
        schema=FLOW_SCHEMA,
    )
    events = pl.DataFrame(
        {
            "tx_hash": [f"0x{20:064x}", f"0x{20:064x}", f"0x{30:064x}"],
            "block_number": [20, 20, 30],
            "receipt_gas_used": [100_000, 100_000, 50_000],
            "receipt_effective_gas_price": [20 * 10**9] * 3,
        }
    )
    gas = gas_by_position(flows, events, PRICES)
    # 100,000 gas x 20 gwei = 0.002 ETH x 2000 = 4 USD, halved; then 50,000 gas x 20 gwei x 2100
    assert gas["direct:j"] == pytest.approx(2.0)
    assert gas["nft:1"] == pytest.approx(2.0 + 2.1)


def test_direct_by_position_splits_builder_payments_like_gas() -> None:
    flows = pl.DataFrame(
        [
            flow("nft:1", 20, "increase", L, 1, 1),
            flow("direct:j", 20, "mint", L, 1, 1),
            flow("nft:1", 30, "decrease", -L, 1, 1),
        ],
        schema=FLOW_SCHEMA,
    )
    tx_direct = pl.DataFrame(
        {"tx_hash": [f"0x{20:064x}", "0x" + "ee" * 32], "direct_wei": [10**15, 10**18]},
        schema={"tx_hash": pl.String, "direct_wei": pl.Decimal(38, 0)},
    )
    # 0.001 ETH x 2000 = 2 USD, halved; transaction 30 paid nothing, 0xee.. touched no position
    assert direct_by_position(flows, tx_direct, PRICES) == {
        "direct:j": pytest.approx(1.0),
        "nft:1": pytest.approx(1.0),
    }


def test_direct_by_position_rejects_a_paying_block_without_a_price() -> None:
    flows = pl.DataFrame([flow("nft:1", 7, "increase", L, 1, 1)], schema=FLOW_SCHEMA)
    tx_direct = pl.DataFrame(
        {"tx_hash": [f"0x{7:064x}"], "direct_wei": [1]},
        schema={"tx_hash": pl.String, "direct_wei": pl.Decimal(38, 0)},
    )
    with pytest.raises(ValueError, match=r"0x0*7 \(block 7\) has no price"):
        direct_by_position(flows, tx_direct, PRICES)


def test_jit_own_swaps_counts_jit_transactions_that_also_swap() -> None:
    positions = pl.DataFrame(
        {
            "position_id": ["a", "b", "c"],
            "lp_type": ["jit", "jit", "nft_wallet"],
            "gas_usd": [1.0, 2.0, 4.0],
            "direct_usd": [0.5, 0.0, 8.0],
        }
    )
    flows = pl.DataFrame({"position_id": ["a", "a", "b", "c"], "tx_hash": ["t1", "t1", "t2", "t3"]})
    swaps = pl.DataFrame(
        {"tx_hash": ["t1", "t1", "t3", "t9"], "markout_usd_0": [-3.0, -1.0, -50.0, 7.0]}
    )
    out = jit_own_swaps(positions, flows, swaps)
    assert out == {
        "jit_txs": 2,
        "jit_txs_with_own_swaps": 1,
        "own_swaps": 2,
        "own_swap_markout_usd_0": pytest.approx(-4.0),
        "gas_usd_in_txs_with_own_swaps": pytest.approx(1.0),
        "direct_usd_in_txs_with_own_swaps": pytest.approx(0.5),
    }


def test_position_closed_inside_the_window_is_priced_at_its_exit_block() -> None:
    positions = pl.DataFrame([pos("nft:1", "nft", NPM_ADDRESS, WALLET, 1)], schema=POSITION_SCHEMA)
    accounts = pl.DataFrame([acc("nft:1", L, 0, (0, 0), 1.0, 0.25)], schema=ACCOUNT_SCHEMA)
    flows = pl.DataFrame([flow("nft:1", 30, "decrease", -L, 500, 5 * 10**14)], schema=FLOW_SCHEMA)
    df = window_pnl(
        positions, accounts, flows, PRICES, {}, {"nft:1": 10.0}, {WALLET}, {}, START, END
    )
    r = df.row(0, named=True)
    d0, d1 = position_amounts(L, -10, 10, START.sqrt_price_x96)
    assert r["lp_type"] == "lp_vault" and r["cohort"] == "pre_window"
    assert r["holding"] == "<1h" and r["exit_block"] == 30
    assert r["pnl_hold_usd"] == pytest.approx(usd(500 - d0, 5 * 10**14 - d1, 2100.0))
    assert r["days_active"] == pytest.approx((360 - 12) / 86400)


def test_window_pnl_without_active_accounts_keeps_the_schema() -> None:
    accounts = pl.DataFrame([acc("nft:2", 0, 0, (0, 0), 0.0, 0.0, False)], schema=ACCOUNT_SCHEMA)
    df = window_pnl(
        pl.DataFrame([pos("nft:2", "nft", NPM_ADDRESS, WALLET, 2)], schema=POSITION_SCHEMA),
        accounts,
        pl.DataFrame(schema=FLOW_SCHEMA),
        PRICES,
        {},
        {},
        set(),
        {},
        START,
        END,
    )
    assert df.height == 0 and df.columns == PNL_COLUMNS


def test_bootstrap_is_reproducible_and_handles_empty_input() -> None:
    num, den = np.array([1.0, 3.0, 2.0]), np.array([100.0, 100.0, 50.0])
    assert bootstrap_ratio(num, den) == bootstrap_ratio(num, den)
    assert all(math.isnan(x) for x in bootstrap_ratio(np.array([]), np.array([])))


def _gas_inputs(
    tx_hash: str = f"0x{20:064x}",
    gas_used: int | None = 100_000,
    gas_price: int | None = 20 * 10**9,
    block: int = 20,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    flows = pl.DataFrame([flow("nft:1", block, "increase", L, 1, 1)], schema=FLOW_SCHEMA)
    events = pl.DataFrame(
        {
            "tx_hash": [tx_hash],
            "block_number": [block],
            "receipt_gas_used": [gas_used],
            "receipt_effective_gas_price": [gas_price],
        },
        schema={
            "tx_hash": pl.String,
            "block_number": pl.Int64,
            "receipt_gas_used": pl.Int64,
            "receipt_effective_gas_price": pl.Int64,
        },
    )
    return flows, events


def test_gas_by_position_accepts_a_complete_receipt() -> None:
    assert gas_by_position(*_gas_inputs(), PRICES) == {"nft:1": pytest.approx(4.0)}


def test_gas_by_position_rejects_a_flow_without_a_receipt() -> None:
    flows, events = _gas_inputs(tx_hash="0x" + "ee" * 32)
    with pytest.raises(ValueError, match=r"0x0*14 \(block 20\) has no receipt"):
        gas_by_position(flows, events, PRICES)


def test_gas_by_position_rejects_a_block_without_a_price() -> None:
    flows, events = _gas_inputs(tx_hash=f"0x{7:064x}", block=7)
    with pytest.raises(ValueError, match=r"0x0*7 \(block 7\) has no price"):
        gas_by_position(flows, events, PRICES)


@pytest.mark.parametrize("missing", ["gas_used", "gas_price"])
def test_gas_by_position_rejects_null_gas_fields(missing: str) -> None:
    kwargs: dict[str, Any] = {missing: None}
    flows, events = _gas_inputs(**kwargs)
    with pytest.raises(ValueError, match=r"\(block 20\) has a null gas"):
        gas_by_position(flows, events, PRICES)


def test_position_without_a_grid_point_is_valued_at_its_first_deposit() -> None:
    prices = {**PRICES, 35: (420 * US, 2000.0)}
    positions = pl.DataFrame([pos("direct:x", "direct", DIRECT, DIRECT)], schema=POSITION_SCHEMA)
    accounts = pl.DataFrame([acc("direct:x", 0, 0, (0, 0), 1.0, 0.5)], schema=ACCOUNT_SCHEMA)
    flows = pl.DataFrame(
        [
            flow("direct:x", 20, "mint", L, 2_000_000, 10**15),
            flow("direct:x", 25, "burn", -L, 2_000_000, 10**15),
            flow("direct:x", 30, "mint", L, 5_000_000, 0),
            flow("direct:x", 35, "burn", -L, 5_000_000, 0),
        ],
        schema=FLOW_SCHEMA,
    )
    df = window_pnl(positions, accounts, flows, prices, {}, {}, set(), {}, START, END)
    r = df.row(0, named=True)
    assert r["twv_usd"] == pytest.approx(usd(2_000_000, 10**15, 2000.0))  # not the sum of both


def test_time_weighted_value_reads_the_last_change_at_a_timestamp() -> None:
    grid = pl.DataFrame(
        {
            "ts_us": [k * 3600 * US for k in range(4)],
            "sqrt": [sqrt_at(0) / Q96] * 4,
            "p_cex": [2000.0] * 4,
        }
    )
    schema = {"position_id": pl.String, "ts_us": pl.Int64, "liquidity": pl.Int128}
    # two changes at t = 0 (event order: L, then 2L), a third between grid points 1 and 2
    path = pl.DataFrame(
        {
            "position_id": ["p", "p", "p"],
            "ts_us": [0, 0, 5400 * US],
            "liquidity": [L, 2 * L, 4 * L],
        },
        schema=schema,
    )
    spans = pl.DataFrame(
        {
            "position_id": ["p"],
            "tick_lower": [-10],
            "tick_upper": [10],
            "t_start_us": [0],
            "t_exit_us": [12600 * US],
        }
    )
    twv = dict(time_weighted_value(path, spans, grid).iter_rows())
    unit = usd(*position_amounts(L, -10, 10, sqrt_at(0)), 2000.0)
    assert twv["p"] == pytest.approx(unit * (2 + 2 + 4 + 4) / 4, rel=1e-9)


def test_jit_per_swap_counts_the_swaps_between_mint_and_burn() -> None:
    positions = pl.DataFrame(
        {
            "position_id": ["a", "b", "d", "c"],
            "lp_type": ["jit", "jit", "jit", "nft_wallet"],
            "fee_usd": [1.0, 0.5, 0.0, 9.0],
            "lvr_0": [-6.0, 1.0, 0.0, 9.0],
            "gas_usd": [1.0, 0.5, 2.0, 9.0],
            "direct_usd": [0.5, 0.0, 1.0, 9.0],
            "pnl_rebal_usd": [6.0, -1.0, -2.0, 9.0],
            "pnl_hold_usd": [6.5, -1.0, -2.0, 9.0],
        }
    )
    flows = pl.DataFrame(
        {
            "position_id": ["a", "a", "a", "b", "b", "d", "d", "c"],
            "block_number": [5] * 8,
            "pool_log_index": [1, 4, 5, 7, 9, 10, 11, 0],
            "liquidity_delta": [10, -10, 0, 3, -3, 2, -2, 50],
        },
        schema_overrides={"liquidity_delta": pl.Int128},
    )
    swaps = pl.DataFrame(
        {"block_number": [5, 5, 5, 5, 6], "log_index": [2, 3, 6, 8, 2]}
    )  # a covers 2 and 3, b covers 8, d none; 6 and block 6 fall outside every JIT span
    j = jit_per_swap(positions, flows, swaps)
    assert j["positions"] == 3 and j["positions_with_swaps"] == 2 and j["swaps"] == 3
    assert j["fee_usd_per_swap"] == pytest.approx(0.5)
    assert j["lvr_0_usd_per_swap"] == pytest.approx(-5.0 / 3)
    assert j["gas_usd_per_swap"] == pytest.approx(3.5 / 3)
    assert j["direct_usd_per_swap"] == pytest.approx(1.5 / 3)
    assert j["pnl_rebal_usd_per_swap"] == pytest.approx(1.0)
    assert j["pnl_hold_usd_per_swap"] == pytest.approx(3.5 / 3)
    assert j["median_pnl_rebal_usd_per_swap"] == pytest.approx(1.0)  # a: 6/2 = 3, b: -1/1
    none = jit_per_swap(positions.filter(pl.col("lp_type") != "jit"), flows, swaps)
    assert none["positions"] == 0 and none["swaps"] == 0
    assert none["pnl_rebal_usd_per_swap"] is None


def test_tx_receipts_keeps_one_row_per_transaction() -> None:
    events = pl.DataFrame(
        {
            "tx_hash": ["0x1", "0x1", "0x2"],
            "receipt_gas_used": [10, 10, 20],
            "receipt_effective_gas_price": [3, 3, 4],
        }
    )
    r = tx_receipts(events).sort("tx_hash")
    assert r.columns == ["tx_hash", "receipt_gas_used", "receipt_effective_gas_price"]
    assert r.rows() == [("0x1", 10, 3), ("0x2", 20, 4)]
