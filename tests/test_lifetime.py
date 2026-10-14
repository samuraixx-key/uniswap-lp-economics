from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics.config import NPM_ADDRESS
from uniswap_lp_economics.lp.ledger import ACCOUNT_SCHEMA
from uniswap_lp_economics.lp.lifetime import life_bucket, lifetime_summary, lifetime_table
from uniswap_lp_economics.lp.pnl import Edge, position_amounts, usd
from uniswap_lp_economics.lp.positions import FLOW_SCHEMA, POSITION_SCHEMA
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at

L = 10**18
US = 1_000_000
DAY = 86_400 * US
WINDOW_START = 400 * DAY


def flow(pid: str, block: int, ts: int, event: str, delta: int, a0: int, a1: int) -> dict[str, Any]:
    return {
        "position_id": pid,
        "kind": "nft",
        "token_id": 1,
        "block_number": block,
        "log_index": 0,
        "pool_log_index": 0,
        "tx_hash": "0x",
        "ts_us": ts,
        "event": event,
        "liquidity_delta": delta,
        "amount0": a0,
        "amount1": a1,
    }


def test_lifetime_of_a_position_opened_before_the_window() -> None:
    positions = pl.DataFrame(
        [
            {
                "position_id": "nft:1",
                "kind": "nft",
                "token_id": 1,
                "owner": NPM_ADDRESS,
                "tick_lower": -10,
                "tick_upper": 10,
                "lp": "0x" + "a1" * 20,
                "transferred": False,
                "first_block": 5,
                "first_ts_us": 10 * DAY,
                "close_block": None,
                "close_ts_us": None,
            }
        ],
        schema=POSITION_SCHEMA,
    )
    flows = pl.DataFrame(
        [
            flow("nft:1", 5, 10 * DAY, "increase", L, 1000, 10**15),
            flow("nft:1", 7, 20 * DAY, "collect", 0, 30, 0),
        ],
        schema=FLOW_SCHEMA,
    )
    accounts = pl.DataFrame(
        [
            {
                "position_id": "nft:1",
                "liquidity_start": L,
                "liquidity_end": L,
                "active": True,
                "carried_owed": True,
                "fees_raw0": 0,
                "fees_raw1": 0,
                "fee_usd": 0.0,
                "lvr_0": 0.0,
                "lvr_12": 0.0,
                "owed_end0": 4,
                "owed_end1": 0,
                "pending_end0": 6,
                "pending_end1": 0,
            }
        ],
        schema=ACCOUNT_SCHEMA,
    )
    minute = pl.DataFrame({"ts_us": [10 * DAY - 60 * US], "price": [1500.0]})
    end = Edge(900, 410 * DAY, sqrt_at(0), 2000.0)
    life = lifetime_table(positions, flows, accounts, ["nft:1"], {}, minute, WINDOW_START, end)
    row = life.row(0, named=True)
    e0, e1 = position_amounts(L, -10, 10, sqrt_at(0))
    expected = usd(30 + 4 + 6 + e0 - 1000, e1 - 10**15, 2000.0)
    assert row["pnl_hold_life_usd"] == pytest.approx(expected)
    assert row["deposits_usd"] == pytest.approx(usd(1000, 10**15, 1500.0))
    assert row["life_bucket"] == ">=180d"
    overall, by_width, by_life = lifetime_summary(life)
    assert overall["positions"] == 1
    assert by_life["life_bucket"].to_list() == [">=180d"]


def test_life_bucket() -> None:
    assert [
        life_bucket(s) for s in (3600.0, 2 * 86400.0, 10 * 86400.0, 60 * 86400.0, 200 * 86400.0)
    ] == ["<1d", "1-7d", "7-30d", "30-180d", ">=180d"]


def test_closed_position_uses_window_prices_and_last_removal() -> None:
    positions = pl.DataFrame(
        [
            {
                "position_id": "nft:2",
                "kind": "nft",
                "token_id": 2,
                "owner": NPM_ADDRESS,
                "tick_lower": -10,
                "tick_upper": 10,
                "lp": "0x" + "b2" * 20,
                "transferred": False,
                "first_block": 800,
                "first_ts_us": WINDOW_START + DAY // 2,
                "close_block": 810,
                "close_ts_us": WINDOW_START + DAY,
            }
        ],
        schema=POSITION_SCHEMA,
    )
    flows = pl.DataFrame(
        [
            flow("nft:2", 800, WINDOW_START + DAY // 2, "mint", L, 1000, 10**15),
            flow("nft:2", 810, WINDOW_START + DAY, "decrease", -L, 1500, 10**15),
            flow("nft:2", 810, WINDOW_START + DAY, "collect", 0, 1500, 10**15),
        ],
        schema=FLOW_SCHEMA,
    ).with_columns(log_index=pl.Series([0, 1, 2]))
    accounts = pl.DataFrame(
        [
            {
                "position_id": "nft:2",
                "liquidity_start": 0,
                "liquidity_end": 0,
                "active": True,
                "carried_owed": False,
                "fees_raw0": 0,
                "fees_raw1": 0,
                "fee_usd": 0.0,
                "lvr_0": 0.0,
                "lvr_12": 0.0,
                "owed_end0": 0,
                "owed_end1": 0,
                "pending_end0": 0,
                "pending_end1": 0,
            }
        ],
        schema=ACCOUNT_SCHEMA,
    )
    prices = {800: (0, 1800.0), 810: (0, 2100.0)}
    minute = pl.DataFrame({"ts_us": [0], "price": [1.0]})
    end = Edge(900, WINDOW_START + 10 * DAY, sqrt_at(0), 9999.0)
    life = lifetime_table(positions, flows, accounts, ["nft:2"], prices, minute, WINDOW_START, end)
    row = life.row(0, named=True)
    assert row["pnl_hold_life_usd"] == pytest.approx(usd(500, 0, 2100.0))
    assert row["deposits_usd"] == pytest.approx(usd(1000, 10**15, 1800.0))
    assert row["life_s"] == pytest.approx(DAY / 2 / US)
    assert row["life_bucket"] == "<1d"
    assert row["beat_hold"]


def test_empty_lifetime_summary_keeps_its_columns() -> None:
    empty = pl.DataFrame(schema=FLOW_SCHEMA)
    end = Edge(900, WINDOW_START, sqrt_at(0), 2000.0)
    life = lifetime_table(
        pl.DataFrame(schema=POSITION_SCHEMA),
        empty,
        pl.DataFrame(schema=ACCOUNT_SCHEMA),
        [],
        {},
        pl.DataFrame({"ts_us": [0], "price": [1.0]}),
        WINDOW_START,
        end,
    )
    overall, by_width, by_life = lifetime_summary(life)
    assert overall["positions"] == 0
    assert by_width.height == 0 and by_life.height == 0


def pos_row(pid: str, kind: str, first_ts: int, **extra: Any) -> dict[str, Any]:
    return {
        "position_id": pid,
        "kind": kind,
        "token_id": None if kind == "direct" else 1,
        "owner": "0x" + "d1" * 20,
        "tick_lower": -10,
        "tick_upper": 10,
        "lp": "0x" + "d1" * 20,
        "transferred": False,
        "first_block": 800,
        "first_ts_us": first_ts,
        "close_block": None,
        "close_ts_us": None,
        "carry_out": False,
        "carry_in": False,
    } | extra


def acct_row(pid: str, liquidity_end: int) -> dict[str, Any]:
    return {
        "position_id": pid,
        "liquidity_start": 0,
        "liquidity_end": liquidity_end,
        "active": True,
        "carried_owed": False,
        "fees_raw0": 0,
        "fees_raw1": 0,
        "fee_usd": 0.0,
        "lvr_0": 0.0,
        "lvr_12": 0.0,
        "owed_end0": 0,
        "owed_end1": 0,
        "pending_end0": 0,
        "pending_end1": 0,
    }


def dflow(
    pid: str, block: int, ts: int, event: str, delta: int, a0: int, a1: int
) -> dict[str, Any]:
    return flow(pid, block, ts, event, delta, a0, a1) | {"kind": "direct", "token_id": None}


T_IN = WINDOW_START + DAY // 2
PRICES = {800: (0, 1800.0), 810: (0, 2100.0)}
MINUTE = pl.DataFrame({"ts_us": [0], "price": [1.0]})
END = Edge(900, WINDOW_START + 10 * DAY, sqrt_at(0), 2000.0)


def test_direct_carry_pair_is_flagged_and_left_out_of_the_summary() -> None:
    a, b, c = "direct:x:0", "direct:x:1", "direct:y:0"
    positions = pl.DataFrame(
        [
            pos_row(a, "direct", T_IN, carry_out=True),
            pos_row(b, "direct", T_IN, carry_in=True),
            pos_row(c, "direct", T_IN),
        ],
        schema=POSITION_SCHEMA,
    )
    flows = pl.DataFrame(
        [
            dflow(a, 800, T_IN, "mint", L, 1000, 10**15),
            dflow(a, 810, T_IN + DAY, "burn", -L, 1000, 10**15),  # never collected
            dflow(b, 800, T_IN, "mint", L, 1000, 10**15),
            dflow(b, 810, T_IN + DAY, "burn", -L, 1000, 10**15),
            dflow(b, 810, T_IN + DAY, "collect", 0, 2000, 2 * 10**15),  # collects both
            dflow(c, 800, T_IN, "mint", L, 1000, 10**15),
            dflow(c, 810, T_IN + DAY, "burn", -L, 1500, 10**15),
            dflow(c, 810, T_IN + DAY, "collect", 0, 1500, 10**15),
        ],
        schema=FLOW_SCHEMA,
    ).with_columns(log_index=pl.Series(range(8)))
    accounts = pl.DataFrame([acct_row(x, 0) for x in (a, b, c)], schema=ACCOUNT_SCHEMA)
    life = lifetime_table(positions, flows, accounts, [a, b, c], PRICES, MINUTE, WINDOW_START, END)
    assert life["carry_flag"].to_list() == [True, True, False]
    # the handed-on episodes show the distorted returns the flag exists for
    assert life.filter(pl.col("position_id") == a)["pnl_hold_life_usd"].item() < 0
    overall, by_width, by_life = lifetime_summary(life)
    assert overall["positions"] == 3
    assert overall["n_excluded_carry"] == 2
    assert overall["share_beat_hold"] == 1.0
    kept_return = life.filter(pl.col("position_id") == c)["return_life"].item()
    assert overall["median_return"] == pytest.approx(kept_return)
    assert by_width["positions"].sum() == 1
    assert by_life["positions"].sum() == 1


def test_pre_window_deposit_with_a_stale_one_minute_close_raises() -> None:
    pid = "nft:1"
    positions = pl.DataFrame([pos_row(pid, "nft", 10 * DAY)], schema=POSITION_SCHEMA)
    flows = pl.DataFrame([flow(pid, 5, 10 * DAY, "increase", L, 1000, 10**15)], schema=FLOW_SCHEMA)
    accounts = pl.DataFrame([acct_row(pid, L)], schema=ACCOUNT_SCHEMA)
    stale = pl.DataFrame({"ts_us": [10 * DAY - 7200 * US], "price": [1500.0]})
    with pytest.raises(ValueError, match="nft:1.*1-minute close"):
        lifetime_table(positions, flows, accounts, [pid], {}, stale, WINDOW_START, END)
    before_first = pl.DataFrame({"ts_us": [11 * DAY], "price": [1500.0]})
    with pytest.raises(ValueError, match="nft:1.*1-minute close"):
        lifetime_table(positions, flows, accounts, [pid], {}, before_first, WINDOW_START, END)


def test_in_window_deposit_without_a_price_raises() -> None:
    pid = "nft:1"
    positions = pl.DataFrame([pos_row(pid, "nft", T_IN)], schema=POSITION_SCHEMA)
    flows = pl.DataFrame([flow(pid, 800, T_IN, "increase", L, 1000, 10**15)], schema=FLOW_SCHEMA)
    accounts = pl.DataFrame([acct_row(pid, L)], schema=ACCOUNT_SCHEMA)
    with pytest.raises(ValueError, match="nft:1.*block 800"):
        lifetime_table(positions, flows, accounts, [pid], {}, MINUTE, WINDOW_START, END)


def test_closed_position_without_a_removal_raises() -> None:
    pid = "nft:1"
    positions = pl.DataFrame([pos_row(pid, "nft", T_IN)], schema=POSITION_SCHEMA)
    flows = pl.DataFrame([flow(pid, 800, T_IN, "increase", L, 1000, 10**15)], schema=FLOW_SCHEMA)
    accounts = pl.DataFrame([acct_row(pid, 0)], schema=ACCOUNT_SCHEMA)
    with pytest.raises(ValueError, match="nft:1.*no removal"):
        lifetime_table(positions, flows, accounts, [pid], PRICES, MINUTE, WINDOW_START, END)
