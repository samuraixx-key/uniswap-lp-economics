from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics.io import u256_hex
from uniswap_lp_economics.lp.checks import check_l2
from uniswap_lp_economics.lp.engine import (
    EngineRow,
    SwapContext,
    iter_engine_rows,
    replay_window,
)
from uniswap_lp_economics.lp.state import FeeAccumulators, PoolState
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import swap

L = 10**18
T0 = datetime(2026, 7, 1, tzinfo=UTC)
SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "block_timestamp": pl.Datetime("us", "UTC"),
    "tx_hash": pl.String,
    "event": pl.String,
    "owner": pl.String,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "amount": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
    "sqrt_price_x96": pl.Int128,
    "tick": pl.Int64,
    "liquidity": pl.Int128,
}
OWNER = "0x" + "aa" * 20


def fresh() -> PoolState:
    return PoolState(TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0), FeeAccumulators(), 0)


def window_events() -> pl.DataFrame:
    probe = fresh()
    probe.mint(-10, 10, L)
    run = swap(probe.book, True, 10**14)
    rows = [
        {
            "block_number": 1,
            "log_index": 0,
            "event": "mint",
            "owner": OWNER,
            "tick_lower": -10,
            "tick_upper": 10,
            "amount": L,
            "amount0": 1,
            "amount1": 1,
        },
        {
            "block_number": 2,
            "log_index": 0,
            "event": "swap",
            "amount0": run.amount_in,
            "amount1": -run.amount_out,
            "sqrt_price_x96": run.sqrt_price_x96,
            "tick": run.tick,
            "liquidity": run.liquidity,
        },
        {
            "block_number": 3,
            "log_index": 0,
            "event": "burn",
            "owner": OWNER,
            "tick_lower": -10,
            "tick_upper": 10,
            "amount": L // 2,
            "amount0": 1,
            "amount1": 1,
        },
    ]
    for r in rows:
        r["block_timestamp"] = T0
        r["tx_hash"] = f"0x{r['block_number']:064x}"
    return pl.DataFrame(rows, schema=SCHEMA)


CONTEXTS = {(2, 0): SwapContext(2000.0, 2001.0, "searcher", int(T0.timestamp()) * 1_000_000)}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def start(self, state: PoolState) -> None:
        self.calls.append(("start", None))

    def on_pool_event(self, row: EngineRow, state: PoolState) -> None:
        # mint: the ticks already exist; burn: they still exist
        assert -10 in state.acc.outside0
        self.calls.append(("pool", (row.event, state.book.liquidity)))

    def on_npm_event(self, row: EngineRow, state: PoolState) -> None:
        self.calls.append(("npm", row.event))

    def new_day(self, day: date, state: PoolState) -> None:
        self.calls.append(("day", day))

    def finish(self, state: PoolState) -> None:
        self.calls.append(("finish", None))


def test_iter_engine_rows_merges_and_drops_transfers() -> None:
    npm = pl.DataFrame(
        {
            "block_number": [1, 1],
            "log_index": [1, 2],
            "block_timestamp": [T0, T0],
            "tx_hash": ["0x01", "0x01"],
            "event": ["transfer", "increase"],
            "token_id": [7, 7],
            "liquidity": [None, L],
        },
        schema={
            **{
                k: SCHEMA[k]
                for k in (
                    "block_number",
                    "log_index",
                    "block_timestamp",
                    "tx_hash",
                    "event",
                    "liquidity",
                )
            },
            "token_id": pl.Int64,
        },
    )
    rows = list(iter_engine_rows(window_events(), npm))
    assert [(r.source, r.event) for r in rows] == [
        ("pool", "mint"),
        ("npm", "increase"),
        ("pool", "swap"),
        ("pool", "burn"),
    ]
    assert rows[1].token_id == 7 and rows[1].liquidity == L and rows[0].owner == OWNER


def test_replay_window_accumulates_calls_hooks_and_captures() -> None:
    st = fresh()
    rec = Recorder()
    run = replay_window(window_events(), st, CONTEXTS, capture={2: [-10, 10]}, ledger=rec)
    assert run.modes == {"exact_input": 1}
    # tick 0 is a bitmap-word boundary: V3 first takes a zero-length step, then the real one
    assert run.steps["amount_in"].to_list()[0] == 0 and run.steps.height == 2
    assert run.steps["flow_label"].to_list() == ["searcher"] * 2
    assert rec.calls[0] == ("start", None) and rec.calls[-1] == ("finish", None)
    assert ("pool", ("mint", L)) in rec.calls  # mint applied before the hook
    assert ("pool", ("burn", L)) in rec.calls  # burn hook before the burn
    assert st.book.liquidity == L // 2
    cap = run.captures[2]
    assert cap["global0"] == st.acc.global0 and cap["ticks"][-10] == (0, 0)


def test_replay_window_needs_a_reference_for_every_swap() -> None:
    with pytest.raises(ValueError, match="no reference price for the swap at block 2 log 0"):
        replay_window(window_events(), fresh(), {})


def test_l2_compares_captures_with_chain_rows() -> None:
    st = fresh()
    run = replay_window(window_events(), st, CONTEXTS, capture={2: [-10]})
    cap = run.captures[2]
    rows = pl.DataFrame(
        [
            {
                "block": 2,
                "kind": "global",
                "tick": None,
                "fee_growth0": u256_hex(cap["global0"]),
                "fee_growth1": u256_hex(cap["global1"]),
            },
            {
                "block": 2,
                "kind": "tick",
                "tick": -10,
                "fee_growth0": u256_hex(0),
                "fee_growth1": u256_hex(0),
            },
        ],
        schema={
            "block": pl.Int64,
            "kind": pl.String,
            "tick": pl.Int64,
            "fee_growth0": pl.String,
            "fee_growth1": pl.String,
        },
    )
    assert check_l2(run.captures, rows).passed
    bad = rows.with_columns(fee_growth0=pl.lit(u256_hex(1)))
    r = check_l2(run.captures, bad)
    assert not r.passed and r.summary["mismatches"] == 2
