from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl

from uniswap_lp_economics.config import NPM_ADDRESS
from uniswap_lp_economics.data.chain_state import POSITION_STATE_SCHEMA
from uniswap_lp_economics.io import u256_hex
from uniswap_lp_economics.lp.checks import check_l3, check_l4
from uniswap_lp_economics.lp.engine import SwapContext, replay_window
from uniswap_lp_economics.lp.ledger import Ledger
from uniswap_lp_economics.lp.positions import build_positions
from uniswap_lp_economics.lp.state import Q128, FeeAccumulators, PoolState
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import SwapRun, swap

L = 10**18
T0 = datetime(2026, 7, 1, tzinfo=UTC)
DIRECT = "0x" + "d1" * 20
OTHER = "0x" + "d2" * 20
POOL: dict[str, Any] = {
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
NPM: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "block_timestamp": pl.Datetime("us", "UTC"),
    "tx_hash": pl.String,
    "event": pl.String,
    "token_id": pl.Int64,
    "liquidity": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
    "from_owner": pl.String,
    "to_owner": pl.String,
}


def ts(block: int) -> datetime:
    return T0 + timedelta(days=block // 10, seconds=block)  # blocks 10+ fall on the next day


def pool_row(block: int, log: int, event: str, **kw: Any) -> dict[str, Any]:
    return {
        "block_number": block,
        "log_index": log,
        "block_timestamp": ts(block),
        "tx_hash": f"0x{block:064x}",
        "event": event,
        **kw,
    }


def npm_row(block: int, log: int, event: str, **kw: Any) -> dict[str, Any]:
    return {
        "block_number": block,
        "log_index": log,
        "block_timestamp": ts(block),
        "tx_hash": f"0x{block:064x}",
        "event": event,
        **kw,
    }


def fresh() -> PoolState:
    return PoolState(TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0), FeeAccumulators(), 0)


def a_swap(probe_liquidity: int = L) -> SwapRun:
    probe = fresh()
    probe.mint(-10, 10, probe_liquidity)
    return swap(probe.book, True, 10**15)


def swap_row(block: int, run: SwapRun) -> dict[str, Any]:
    return pool_row(
        block,
        0,
        "swap",
        amount0=run.amount_in,
        amount1=-run.amount_out,
        sqrt_price_x96=run.sqrt_price_x96,
        tick=run.tick,
        liquidity=run.liquidity,
    )


def ctx(block: int) -> SwapContext:
    return SwapContext(2000.0, 2000.0, "searcher", int(ts(block).timestamp()) * 1_000_000)


def owed_for(run: SwapRun) -> int:
    return L * (run.fee * Q128 // L) // Q128


def key_row(owner: str, liquidity: int, last0: int, owed0: int, owed1: int = 0) -> dict[str, Any]:
    return {
        "block": 9,
        "kind": "pool_key",
        "owner": owner,
        "tick_lower": -10,
        "tick_upper": 10,
        "token_id": None,
        "found": True,
        "liquidity": liquidity,
        "fee_growth_inside0_last": u256_hex(last0),
        "fee_growth_inside1_last": u256_hex(0),
        "tokens_owed0": owed0,
        "tokens_owed1": owed1,
    }


def noop_collect_row(block: int, log: int) -> dict[str, Any]:
    return pool_row(
        block,
        log,
        "collect",
        owner=OTHER,
        tick_lower=0,
        tick_upper=0,
        amount=0,
        amount0=0,
        amount1=0,
    )


def direct_case(extra: int = 0, noop: bool = False) -> tuple[Ledger, int, int]:
    run = a_swap()
    owed = owed_for(run)
    extras = [noop_collect_row(1, 1), noop_collect_row(2, 1)] if noop else []
    rows = [
        pool_row(
            1,
            0,
            "mint",
            owner=DIRECT,
            tick_lower=-10,
            tick_upper=10,
            amount=L,
            amount0=7,
            amount1=8,
        ),
        swap_row(2, run),
        pool_row(
            3,
            0,
            "burn",
            owner=DIRECT,
            tick_lower=-10,
            tick_upper=10,
            amount=L,
            amount0=5,
            amount1=6,
        ),
        pool_row(
            3,
            1,
            "collect",
            owner=DIRECT,
            tick_lower=-10,
            tick_upper=10,
            amount=0,
            amount0=5 + owed + extra,
            amount1=6,
        ),
    ]
    rows = sorted(rows + extras, key=lambda r: (r["block_number"], r["log_index"]))
    events = pl.DataFrame(rows, schema=POOL)
    data = build_positions(events, pl.DataFrame(schema=NPM))
    ledger = Ledger(data, pl.DataFrame(schema=POSITION_STATE_SCHEMA), 0)
    replay_window(events, fresh(), {(2, 0): ctx(2)}, ledger=ledger)
    return ledger, owed, run.fee


def test_direct_position_fees_equal_collect_minus_principal() -> None:
    ledger, owed, _ = direct_case()
    acc = ledger.accounts[f"direct:{DIRECT}:-10:10:0"]
    assert acc.fees0 == owed and acc.fees1 == 0
    km = ledger.keys[(DIRECT, -10, 10)]
    assert (km.liquidity, km.owed0, km.owed1) == (0, 0, 0)
    end = pl.DataFrame([key_row(DIRECT, 0, km.last0, 0)], schema=POSITION_STATE_SCHEMA)
    assert check_l3(ledger, end).passed
    r = check_l4(ledger, end, 0)
    assert r.passed and r.summary["positions_checked"] == 1


def test_noop_collects_on_never_minted_keys_leave_the_replay_unchanged() -> None:
    plain, owed, _ = direct_case()
    ledger, owed2, _ = direct_case(noop=True)
    assert owed2 == owed
    assert ledger.data.noop_collects == {(1, 1), (2, 1)}
    assert (OTHER, 0, 0) not in ledger.keys
    assert set(ledger.accounts) == set(plain.accounts)
    acc = ledger.accounts[f"direct:{DIRECT}:-10:10:0"]
    assert acc.fees0 == owed and acc.fees1 == 0
    km = ledger.keys[(DIRECT, -10, 10)]
    end = pl.DataFrame([key_row(DIRECT, 0, km.last0, 0)], schema=POSITION_STATE_SCHEMA)
    assert check_l3(ledger, end).passed
    r = check_l4(ledger, end, 0)
    assert r.passed and r.summary["positions_checked"] == 1


def test_l3_and_l4_catch_a_wrong_collect() -> None:
    ledger, _, _ = direct_case(extra=1)
    km = ledger.keys[(DIRECT, -10, 10)]
    end = pl.DataFrame([key_row(DIRECT, 0, km.last0, 0)], schema=POSITION_STATE_SCHEMA)
    assert not check_l3(ledger, end).passed  # the mirror owes -1, the chain 0
    assert not check_l4(ledger, end, 0).passed  # fees != collected - principal


def test_npm_collect_without_liquidity_does_not_accrue() -> None:
    run = a_swap()
    owed = owed_for(run)
    events = pl.DataFrame(
        [
            pool_row(
                1,
                0,
                "mint",
                owner=NPM_ADDRESS,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=7,
                amount1=8,
            ),
            swap_row(2, run),
            pool_row(
                3,
                0,
                "burn",
                owner=NPM_ADDRESS,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=5,
                amount1=6,
            ),
            pool_row(
                4,
                0,
                "collect",
                owner=NPM_ADDRESS,
                tick_lower=-10,
                tick_upper=10,
                amount=0,
                amount0=5 + owed,
                amount1=6,
            ),
        ],
        schema=POOL,
    )
    npm = pl.DataFrame(
        [
            npm_row(1, 1, "increase", token_id=1, liquidity=L, amount0=7, amount1=8),
            npm_row(3, 1, "decrease", token_id=1, liquidity=L, amount0=5, amount1=6),
            npm_row(4, 1, "npm_collect", token_id=1, amount0=5 + owed, amount1=6),  # no poke
        ],
        schema=NPM,
    )
    data = build_positions(events, npm)
    ledger = Ledger(data, pl.DataFrame(schema=POSITION_STATE_SCHEMA), 0)
    replay_window(events, fresh(), {(2, 0): ctx(2)}, ledger=ledger, npm_events=npm)
    tok = ledger.token_mirror(1)
    assert tok is not None and (tok.liquidity, tok.owed0, tok.owed1) == (0, 0, 0)
    assert ledger.accounts["nft:1"].fees0 == owed
    burned = pl.DataFrame(
        [{"block": 9, "kind": "npm_token", "token_id": 1, "found": False}],
        schema=POSITION_STATE_SCHEMA,
    )
    r4 = check_l4(ledger, burned, 0)
    assert r4.passed and r4.summary["positions_checked"] == 1


def test_day_boundary_splits_float_attribution() -> None:
    probe = fresh()
    probe.mint(-10, 10, L)
    first = swap(probe.book, True, 10**14)  # the swaps stay inside the range (a_swap exhausts it)
    probe.book.apply_swap(first.sqrt_price_x96, first.tick)
    second = swap(probe.book, True, 10**14)
    events = pl.DataFrame(
        [
            pool_row(
                1,
                0,
                "mint",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=7,
                amount1=8,
            ),
            swap_row(2, first),
            swap_row(12, second),  # the next day
        ],
        schema=POOL,
    )
    ledger = Ledger(
        build_positions(events, pl.DataFrame(schema=NPM)),
        pl.DataFrame(schema=POSITION_STATE_SCHEMA),
        0,
    )
    replay_window(events, fresh(), {(2, 0): ctx(2), (12, 0): ctx(12)}, ledger=ledger)
    days = ledger.days_frame()
    assert days.height == 2
    acc = ledger.accounts[f"direct:{DIRECT}:-10:10:0"]
    assert days["fee_usd"].sum() == acc.fees_f[0] and acc.fees_f[0] > 0
    assert all(v > 0 for v in days["fee_usd"].to_list())  # both days earned their swap's fees


def test_pre_window_position_starts_from_chain_rows() -> None:
    hist = pl.DataFrame(
        [
            pool_row(
                1,
                0,
                "mint",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=7,
                amount1=8,
            )
        ],
        schema=POOL,
    )
    data = build_positions(hist, pl.DataFrame(schema=NPM))
    st = fresh()
    st.mint(-10, 10, L)  # the snapshot state: the position already exists
    run = swap(st.book, True, 10**15)
    window = pl.DataFrame([swap_row(6, run)], schema=POOL)
    good = pl.DataFrame([key_row(DIRECT, L, 0, 3)], schema=POSITION_STATE_SCHEMA)
    ledger = Ledger(data, good, 5)
    replay_window(window, st, {(6, 0): ctx(6)}, ledger=ledger)
    acc = ledger.accounts[f"direct:{DIRECT}:-10:10:0"]
    assert acc.liquidity_start == L and acc.fees0 == owed_for(run) and not ledger.start_mismatches
    assert ledger.keys[(DIRECT, -10, 10)].owed0 == 3  # carried from the chain, no event since
    wrong = pl.DataFrame([key_row(DIRECT, L // 2, 0, 3)], schema=POSITION_STATE_SCHEMA)
    bad = Ledger(data, wrong, 5)
    st2 = fresh()
    st2.mint(-10, 10, L)
    replay_window(window, st2, {(6, 0): ctx(6)}, ledger=bad)
    assert bad.start_mismatches


def test_remint_before_collect_hands_owed_on() -> None:
    probe = fresh()
    probe.mint(-10, 10, L)
    run1 = swap(probe.book, True, 10**14)
    probe.book.apply_swap(run1.sqrt_price_x96, run1.tick)
    run2 = swap(probe.book, True, 10**14)
    events = pl.DataFrame(
        [
            pool_row(
                1,
                0,
                "mint",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=7,
                amount1=8,
            ),
            swap_row(2, run1),
            pool_row(
                3,
                0,
                "burn",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=5,
                amount1=6,
            ),
            pool_row(
                4,
                0,
                "mint",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=7,
                amount1=8,
            ),
            swap_row(5, run2),
            pool_row(
                6,
                0,
                "burn",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=5,
                amount1=6,
            ),
            pool_row(
                1,
                1,
                "mint",
                owner=OTHER,
                tick_lower=-100,
                tick_upper=-50,
                amount=L,
                amount0=0,
                amount1=9,
            ),
            pool_row(
                3,
                1,
                "burn",
                owner=OTHER,
                tick_lower=-100,
                tick_upper=-50,
                amount=L,
                amount0=0,
                amount1=9,
            ),
            pool_row(
                3,
                2,
                "collect",
                owner=OTHER,
                tick_lower=-100,
                tick_upper=-50,
                amount=0,
                amount0=0,
                amount1=9,
            ),
            # one collect takes both episodes' principal and fees
            pool_row(
                6,
                1,
                "collect",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=0,
                amount0=10 + owed_for(run1) + owed_for(run2),
                amount1=12,
            ),
        ],
        schema=POOL,
    )
    ledger = Ledger(
        build_positions(events, pl.DataFrame(schema=NPM)),
        pl.DataFrame(schema=POSITION_STATE_SCHEMA),
        0,
    )
    replay_window(events, fresh(), {(2, 0): ctx(2), (5, 0): ctx(5)}, ledger=ledger)
    old = ledger.accounts[f"direct:{DIRECT}:-10:10:0"]
    new = ledger.accounts[f"direct:{DIRECT}:-10:10:1"]
    assert old.owed_handed_on and not old.carried_owed
    assert new.carried_owed and not new.owed_handed_on
    km = ledger.keys[(DIRECT, -10, 10)]
    assert (km.liquidity, km.owed0, km.owed1) == (0, 0, 0)
    other = ledger.keys[(OTHER, -100, -50)]
    end = pl.DataFrame(
        [
            key_row(DIRECT, 0, km.last0, 0),
            key_row(OTHER, 0, other.last0, 0) | {"tick_lower": -100, "tick_upper": -50},
        ],
        schema=POSITION_STATE_SCHEMA,
    )
    assert check_l3(ledger, end).passed
    r4 = check_l4(ledger, end, 0)
    # the old episode (handed on) and the new one (carried) are skipped; the other key is checked
    assert r4.passed and r4.summary["positions_checked"] == 1
    frame = ledger.accounts_frame()
    assert frame.filter(pl.col("owed_handed_on"))["position_id"].to_list() == [old.position_id]


def test_key_start_row_with_owed_is_carried_by_a_window_mint() -> None:
    run = a_swap()
    events = pl.DataFrame(
        [
            pool_row(
                6,
                0,
                "mint",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=7,
                amount1=8,
            ),
            swap_row(7, run),
            pool_row(
                8,
                0,
                "burn",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=L,
                amount0=5,
                amount1=6,
            ),
            pool_row(
                8,
                1,
                "collect",
                owner=DIRECT,
                tick_lower=-10,
                tick_upper=10,
                amount=0,
                amount0=5 + 3 + owed_for(run),
                amount1=6,
            ),
        ],
        schema=POOL,
    )
    start = pl.DataFrame([key_row(DIRECT, 0, 0, 3)], schema=POSITION_STATE_SCHEMA)
    ledger = Ledger(build_positions(events, pl.DataFrame(schema=NPM)), start, 5)
    replay_window(events, fresh(), {(7, 0): ctx(7)}, ledger=ledger)
    acc = ledger.accounts[f"direct:{DIRECT}:-10:10:0"]
    assert acc.carried_owed and acc.fees0 == owed_for(run)
    km = ledger.keys[(DIRECT, -10, 10)]
    assert (km.liquidity, km.owed0, km.owed1) == (0, 0, 0)
    end = pl.DataFrame([key_row(DIRECT, 0, km.last0, 0)], schema=POSITION_STATE_SCHEMA)
    assert check_l3(ledger, end).passed
