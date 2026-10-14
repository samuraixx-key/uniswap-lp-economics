from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics.config import NPM_ADDRESS
from uniswap_lp_economics.lp.checks import check_l5, check_l7
from uniswap_lp_economics.lp.positions import build_positions, liquidity_at

L = 10**18
T0 = datetime(2026, 6, 1, tzinfo=UTC)
ZERO = "0x" + "00" * 20
ALICE, BOB, DIRECT = "0x" + "a1" * 20, "0x" + "b0" * 20, "0x" + "d1" * 20
POOL_SCHEMA: dict[str, Any] = {
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
}
NPM_SCHEMA: dict[str, Any] = {
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


def p(
    block: int,
    log: int,
    event: str,
    owner: str,
    amount: int = 0,
    a0: int = 0,
    a1: int = 0,
    lo: int = -10,
    hi: int = 10,
) -> dict[str, Any]:
    return {
        "block_number": block,
        "log_index": log,
        "block_timestamp": T0 + timedelta(hours=block),
        "tx_hash": f"0x{block:064x}",
        "event": event,
        "owner": owner,
        "tick_lower": lo,
        "tick_upper": hi,
        "amount": amount,
        "amount0": a0,
        "amount1": a1,
    }


def n(
    block: int,
    log: int,
    event: str,
    token: int,
    liquidity: int | None = None,
    a0: int = 0,
    a1: int = 0,
    frm: str | None = None,
    to: str | None = None,
) -> dict[str, Any]:
    return {
        "block_number": block,
        "log_index": log,
        "block_timestamp": T0 + timedelta(hours=block),
        "tx_hash": f"0x{block:064x}",
        "event": event,
        "token_id": token,
        "liquidity": liquidity,
        "amount0": a0,
        "amount1": a1,
        "from_owner": frm,
        "to_owner": to,
    }


def nft_life() -> tuple[pl.DataFrame, pl.DataFrame]:
    pool = [
        p(1, 0, "mint", NPM_ADDRESS, L, 5, 6),
        p(2, 0, "burn", NPM_ADDRESS, L // 2, 2, 3),
        p(3, 0, "burn", NPM_ADDRESS, 0),  # poke before the collect
        p(3, 1, "collect", NPM_ADDRESS, 0, 4, 5),
        p(5, 0, "burn", NPM_ADDRESS, L // 2, 2, 3),
    ]
    npm = [
        n(1, 1, "transfer", 5, frm=ZERO, to=ALICE),
        n(1, 2, "increase", 5, L, 5, 6),
        n(2, 1, "decrease", 5, L // 2, 2, 3),
        n(3, 2, "npm_collect", 5, None, 4, 5),
        n(4, 0, "transfer", 5, frm=ALICE, to=BOB),
        n(5, 1, "decrease", 5, L // 2, 2, 3),
    ]
    return pl.DataFrame(pool, schema=POOL_SCHEMA), pl.DataFrame(npm, schema=NPM_SCHEMA)


def test_nft_position_is_matched_through_its_life() -> None:
    data = build_positions(*nft_life())
    pos = data.positions.row(0, named=True)
    assert data.positions.height == 1
    assert pos["position_id"] == "nft:5" and pos["kind"] == "nft"
    assert (pos["tick_lower"], pos["tick_upper"]) == (-10, 10)
    assert pos["lp"] == BOB and pos["transferred"] is True
    assert pos["close_block"] == 5
    assert data.flows["event"].to_list() == ["increase", "decrease", "collect", "decrease"]
    assert data.flows["pool_log_index"].to_list() == [0, 0, 1, 0]
    assert len(data.pool_event_position) == 5  # the poke is mapped too
    assert data.token_position == {5: "nft:5"}


def test_direct_key_reuse_starts_a_new_position() -> None:
    pool = pl.DataFrame(
        [
            p(1, 0, "mint", DIRECT, L, 5, 6),
            p(2, 0, "burn", DIRECT, L, 5, 6),
            p(3, 0, "collect", DIRECT, 0, 7, 8),  # old owed: still the first position
            p(4, 0, "mint", DIRECT, 2 * L, 9, 9),
            p(5, 0, "collect", DIRECT, 0, 1, 1),
        ],
        schema=POOL_SCHEMA,
    )
    data = build_positions(pool, pl.DataFrame(schema=NPM_SCHEMA))
    first, second = f"direct:{DIRECT}:-10:10:0", f"direct:{DIRECT}:-10:10:1"
    assert data.positions["position_id"].to_list() == [first, second]
    assert data.pool_event_position[(3, 0)] == first
    assert data.pool_event_position[(5, 0)] == second
    assert data.positions.filter(pl.col("position_id") == first)["close_block"].item() == 2


def test_zero_collect_on_a_never_minted_direct_key_is_a_noop() -> None:
    pool = pl.DataFrame(
        [
            p(1, 0, "collect", DIRECT, 0, 0, 0, lo=0, hi=0),
            p(2, 0, "mint", DIRECT, L, 5, 6),
            p(3, 0, "collect", DIRECT, 0, 0, 0),  # zero, but the key was minted: a real collect
            p(4, 0, "collect", BOB, 0, 0, 0),
        ],
        schema=POOL_SCHEMA,
    )
    data = build_positions(pool, pl.DataFrame(schema=NPM_SCHEMA))
    pid = f"direct:{DIRECT}:-10:10:0"
    assert data.noop_collects == {(1, 0), (4, 0)}
    assert data.positions["position_id"].to_list() == [pid]
    assert data.flows["event"].to_list() == ["mint", "collect"]
    assert data.pool_event_position == {(2, 0): pid, (3, 0): pid}


def test_nonzero_collect_or_any_burn_on_a_never_minted_key_still_raises() -> None:
    schema = pl.DataFrame(schema=NPM_SCHEMA)
    for bad in (
        p(1, 0, "collect", DIRECT, 0, 1, 0),
        p(1, 0, "collect", DIRECT, 0, 0, 1),
        p(1, 0, "burn", DIRECT, 0),
        p(1, 0, "burn", DIRECT, L, 1, 1),
    ):
        pool = pl.DataFrame([bad], schema=POOL_SCHEMA)
        with pytest.raises(ValueError, match="for a position never minted"):
            build_positions(pool, schema)


def test_unmatched_position_manager_pool_event_raises() -> None:
    pool = pl.DataFrame([p(1, 0, "mint", NPM_ADDRESS, L, 5, 6)], schema=POOL_SCHEMA)
    with pytest.raises(ValueError, match="no matching NonfungiblePositionManager event"):
        build_positions(pool, pl.DataFrame(schema=NPM_SCHEMA))


def test_tokens_of_other_pools_are_ignored() -> None:
    npm = pl.DataFrame([n(1, 0, "increase", 9, L, 1, 1)], schema=NPM_SCHEMA)
    data = build_positions(pl.DataFrame(schema=POOL_SCHEMA), npm)
    assert data.positions.height == 0 and data.token_position == {}


def test_liquidity_at_and_l5() -> None:
    data = build_positions(*nft_life())
    start = liquidity_at(data, 2)
    assert start.rows() == [("nft:5", -10, 10, L // 2)]
    ticks = pl.DataFrame(
        {
            "tick": [-10, 10],
            "liquidity_gross": [L // 2, L // 2],
            "liquidity_net": [L // 2, -L // 2],
        },
        schema={"tick": pl.Int64, "liquidity_gross": pl.Int128, "liquidity_net": pl.Int128},
    )
    assert check_l5(start, ticks, {"tick": 0, "liquidity": L // 2}).passed
    bad = check_l5(start, ticks, {"tick": 0, "liquidity": L})
    assert not bad.passed and bad.summary["active_liquidity_matches"] is False


def test_l7_matches_window_events_and_positions() -> None:
    pool, npm = nft_life()
    data = build_positions(pool, npm)
    window = pool.filter(pl.col("block_number") >= 2)
    assert check_l7(window, window, data).passed
    r = check_l7(window, window.filter(pl.col("block_number") != 5), data)
    assert not r.passed and r.summary["missing_in_history"] == 1


def test_l7_passes_with_noop_collects_and_counts_them() -> None:
    pool = pl.DataFrame(
        [
            p(1, 0, "mint", DIRECT, L, 5, 6),
            p(2, 0, "collect", BOB, 0, 0, 0, lo=0, hi=0),
        ],
        schema=POOL_SCHEMA,
    )
    data = build_positions(pool, pl.DataFrame(schema=NPM_SCHEMA))
    r = check_l7(pool, pool, data)
    assert r.passed
    assert r.summary["noop_collects"] == 1 and r.summary["without_position"] == 0
    assert r.summary["window_liquidity_events"] == 2
    # a window event unknown to the ledger is still unassigned
    stray = pool.vstack(pl.DataFrame([p(3, 0, "mint", BOB, L, 1, 1)], schema=POOL_SCHEMA))
    assert not check_l7(stray, stray, data).passed
