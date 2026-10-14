import json
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.checks import (
    check_a1,
    check_a2,
    check_a3,
    check_a4,
    check_a5,
    check_a6,
    write_checks,
)
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import get_amount1_delta, swap_exact_input
from uniswap_lp_economics.validate import CheckResult

L = 10**18
US = 1_000_000
EVENT_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "event": pl.String,
    "tick": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "liquidity": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
}


def book() -> TickBook:
    b = TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0)
    b.apply_mint(-10, 10, L)
    b.apply_mint(10, 20, 2 * L)
    return b


def swap_event(tamper: bool = False) -> pl.DataFrame:
    amount = get_amount1_delta(sqrt_at(0), sqrt_at(10), L, True) * 5 // 4
    r = swap_exact_input(book(), False, amount)
    out = r.amount_out + (r.amount_out // 1000 if tamper else 0)  # tamper: 0.1% more out
    row = {
        "block_number": 1,
        "log_index": 0,
        "event": "swap",
        "tick": r.tick,
        "sqrt_price_x96": r.sqrt_price_x96,
        "liquidity": r.liquidity,
        "amount0": -out,
        "amount1": r.amount_in,
    }
    return pl.DataFrame([row], schema=EVENT_SCHEMA)


def test_a1_passes_on_reproducible_swap_and_fails_on_tampered() -> None:
    ok = check_a1(swap_event(), book(), 0)
    assert ok.passed and ok.summary["bit_exact"] == 1
    bad = check_a1(swap_event(tamper=True), book(), 0)
    assert not bad.passed and bad.summary["outside_tolerance"] == 1


def series(rows: list[tuple[int, int, int, int]]) -> pl.DataFrame:
    """(block, start sqrt, end sqrt, n_events) with constant tick/liquidity."""
    return pl.DataFrame(
        [
            {
                "block_number": b,
                "sqrt_price_x96": s,
                "tick": 0,
                "liquidity": L,
                "end_sqrt_price_x96": e,
                "end_tick": 0,
                "end_liquidity": L,
                "n_events": n,
            }
            for b, s, e, n in rows
        ],
        schema={
            "block_number": pl.Int64,
            "sqrt_price_x96": pl.Int128,
            "tick": pl.Int64,
            "liquidity": pl.Int128,
            "end_sqrt_price_x96": pl.Int128,
            "end_tick": pl.Int64,
            "end_liquidity": pl.Int128,
            "n_events": pl.Int64,
        },
    )


BLOCKS = pl.DataFrame({"block_number": [10, 11, 12]})
EVENTS = pl.DataFrame(
    [{"block_number": 11, "log_index": 0, "event": "swap", "sqrt_price_x96": 7}],
    schema={
        "block_number": pl.Int64,
        "log_index": pl.Int64,
        "event": pl.String,
        "sqrt_price_x96": pl.Int128,
    },
)


def test_a2_complete_and_consistent() -> None:
    good = series([(10, 5, 5, 0), (11, 5, 7, 1), (12, 7, 7, 0)])
    assert check_a2(good, BLOCKS, EVENTS, 10).passed
    assert not check_a2(good.filter(pl.col("block_number") != 11), BLOCKS, EVENTS, 10).passed
    assert not check_a2(
        series([(10, 5, 5, 0), (11, 5, 8, 1), (12, 8, 8, 0)]), BLOCKS, EVENTS, 10
    ).passed
    assert not check_a2(
        series([(10, 5, 6, 0), (11, 6, 7, 1), (12, 7, 7, 0)]), BLOCKS, EVENTS, 10
    ).passed
    assert not check_a2(good, BLOCKS, EVENTS, 9).passed  # block table starts too late


def test_a3_identity() -> None:
    df = pl.DataFrame(
        {
            "markout_usd_0": [9.0, -1.0],
            "lp_markout_usd_0": [-9.25, 0.75],
            "protocol_fee_usd": [0.25, 0.25],
        }
    )
    assert check_a3(df, (0,)).passed
    assert not check_a3(df.with_columns(protocol_fee_usd=pl.lit(0.5)), (0,)).passed


def test_a3_fails_when_a_residual_cannot_be_evaluated() -> None:
    base: dict[str, Any] = {
        "markout_usd_0": [9.0, -1.0],
        "lp_markout_usd_0": [-9.25, 0.75],
        "protocol_fee_usd": [0.25, 0.25],
    }
    null_lp = check_a3(pl.DataFrame({**base, "lp_markout_usd_0": [-9.25, None]}), (0,))
    assert not null_lp.passed
    assert null_lp.summary["values_checked"] == 1 and null_lp.summary["unevaluated"] == 1
    nan_fee = check_a3(pl.DataFrame({**base, "protocol_fee_usd": [0.25, float("nan")]}), (0,))
    assert not nan_fee.passed
    assert nan_fee.summary["values_checked"] == 1 and nan_fee.summary["unevaluated"] == 1
    # a row with no markout at all (missing reference) is not an unevaluated residual
    no_ref = pl.DataFrame({**base, "markout_usd_0": [9.0, None], "lp_markout_usd_0": [-9.25, None]})
    ok = check_a3(no_ref, (0,))
    assert ok.passed and ok.summary["unevaluated"] == 0 and ok.summary["values_checked"] == 1


def test_a4_nulls_only_past_the_data_end() -> None:
    end = 100 * US
    df = pl.DataFrame(
        {
            "t0_us": [10 * US, 95 * US],
            "p_cex_0": [1.0, 1.0],
            "p_cex_12": [1.0, None],  # 95 s + 12 s is past the end: allowed
            "cex_age_s_0": [0.1, 6.0],
        }
    )
    ok = check_a4(df, 0, end, (0, 12))
    assert ok.passed and ok.summary["stale_ref_over_5s_at_0s"] == 1
    bad = df.with_columns(p_cex_0=pl.Series([None, 1.0], dtype=pl.Float64))
    assert not check_a4(bad, 0, end, (0, 12)).passed


def test_a5_reports_other_contract_share_and_top_unlabelled() -> None:
    labelled = pl.DataFrame(
        {
            "flow_label": ["searcher", "other_contract", "other_contract", "router"],
            "notional_usd": [100.0, 50.0, 30.0, 20.0],
            "to_address": ["0xa", "0xb", "0xc", "0xd"],
        }
    )
    r = check_a5(labelled)
    assert r.passed and r.summary["other_contract_notional_share"] == 0.4
    assert [m["address"] for m in r.mismatches] == ["0xb", "0xc"]


def test_a6_counts_miner_transfers_and_payments_in_top_bot_txs() -> None:
    transfers = pl.DataFrame(
        {
            "tx_hash": ["t1", "t1", "t2", "t9"],
            "block_number": [1, 1, 2, 3],
            "to_address": ["m1", "x", "m2", "m3"],
        }
    )
    aligned = pl.DataFrame(
        {
            "tx_hash": ["t1", "t2", "t3"],
            "is_top_bot": [True, True, False],
            "coinbase_usd": [1.0, 0.0, 5.0],
            "tx_scope": ["full", None, "full"],
        }
    )
    blocks = pl.DataFrame({"block_number": [1, 2, 3], "miner": ["m1", "mX", "m3"]})
    r = check_a6(transfers, aligned, blocks)
    assert r.passed
    assert r.summary["top_bot_txs"] == 2
    assert r.summary["transfers_to_miner"] == 1 and r.summary["transfers_to_others"] == 2
    assert r.summary["share_txs_with_coinbase_payment"] == 0.5
    assert r.summary["top_bot_txs_without_scope"] == 1
    none = check_a6(transfers, aligned.filter(~pl.col("is_top_bot")), blocks)
    assert none.summary["share_txs_with_coinbase_payment"] is None


def test_write_checks(tmp_path: Path) -> None:
    status = write_checks([CheckResult("A1", True, {"n": 1})], tmp_path, {"git_commit": "x"})
    assert status == "PASS"
    body = json.loads((tmp_path / "analysis_checks.json").read_text())
    assert body["status"] == "PASS" and body["git_commit"] == "x"
    assert (tmp_path / "analysis_checks.md").read_text().startswith("# Analysis checks: **PASS**")
