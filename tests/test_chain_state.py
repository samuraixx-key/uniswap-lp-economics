from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics import abi
from uniswap_lp_economics.config import NPM_ADDRESS
from uniswap_lp_economics.data import chain_state
from uniswap_lp_economics.io import hex_u256, u256_hex
from uniswap_lp_economics.lp.positions import FLOW_SCHEMA, POSITION_SCHEMA, LedgerData
from uniswap_lp_economics.rpc import (
    FEE_GROWTH_GLOBAL0_CALL,
    FEE_GROWTH_GLOBAL1_CALL,
    npm_positions_call,
)


def words(values: list[int]) -> str:
    return "0x" + "".join(abi.enc_int(v) for v in values)


class FakePool:
    """Answers the pool calls chain_state makes, from fixed per-tick fee values."""

    def __init__(self, uninitialized: set[int] | None = None) -> None:
        self.uninitialized = uninitialized or set()
        self.blocks: list[int] = []

    def multicall(self, calls: list[tuple[str, str]], block: int) -> list[str | None]:
        self.blocks.append(block)
        out: list[str | None] = []
        for _, data in calls:
            if data == FEE_GROWTH_GLOBAL0_CALL:
                out.append(words([2**255 + block]))
            elif data == FEE_GROWTH_GLOBAL1_CALL:
                out.append(words([7]))
            else:  # ticks(int24)
                t = abi.to_int(data[10:])
                init = 0 if t in self.uninitialized else 1
                out.append(words([1, 1, 1000 + t, 2000 + t, 0, 0, 0, init]))
        return out


def test_read_fee_state_rows_are_hex_and_complete() -> None:
    df = chain_state.read_fee_state(FakePool(), 5, [-10, 20])  # type: ignore[arg-type]
    g = df.filter(pl.col("kind") == "global").row(0, named=True)
    assert hex_u256(g["fee_growth0"]) == 2**255 + 5 and hex_u256(g["fee_growth1"]) == 7
    ticks = df.filter(pl.col("kind") == "tick").sort("tick")
    assert ticks["tick"].to_list() == [-10, 20]
    assert [hex_u256(x) for x in ticks["fee_growth0"].to_list()] == [990, 1020]
    assert df["block"].unique().to_list() == [5]


def test_read_fee_state_rejects_an_uninitialized_tick() -> None:
    with pytest.raises(RuntimeError, match="tick 20 is not initialized at block 5"):
        chain_state.read_fee_state(FakePool({20}), 5, [-10, 20])  # type: ignore[arg-type]


def test_fetch_sample_fees_reads_each_block_once(tmp_path: Path) -> None:
    sample_ticks = pl.DataFrame({"block": [8, 8, 9], "tick": [0, 10, -10]})
    pool = FakePool()
    path = chain_state.fetch_sample_fees(pool, tmp_path, sample_ticks)  # type: ignore[arg-type]
    df = pl.read_parquet(path)
    assert sorted(set(pool.blocks)) == [8, 9]
    assert df.filter(pl.col("kind") == "global").height == 2
    assert df.filter(pl.col("block") == 8).filter(pl.col("kind") == "tick")["tick"].to_list() == [
        0,
        10,
    ]


class FakePositions:
    def __init__(self) -> None:
        self.code_calls: list[str] = []

    def multicall(self, calls: list[tuple[str, str]], block: int) -> list[str | None]:
        out: list[str | None] = []
        for _, data in calls:
            if data.startswith(npm_positions_call(0)[:10]):
                token = int(data[10:], 16)
                if token == 99:
                    out.append(None)  # burned NFT: the call reverts
                else:
                    out.append(words([0, 0, 1, 2, 500, -10, 10, 7, 2**250, 3, 4, 5]))
            else:
                out.append(words([11, 2**255, 1, 2, 3]))
        return out

    def get_code(self, address: str, block: int) -> str:
        self.code_calls.append(address)
        return "0x6080" if address.endswith("c0") else "0x"


def test_read_position_state_rows(tmp_path: Path) -> None:
    owner = "0x" + "d1" * 20
    df = chain_state.read_position_state(  # type: ignore[arg-type]
        FakePositions(), 5, [(owner, -10, 10)], [7, 99]
    )
    key = df.filter(pl.col("kind") == "pool_key").row(0, named=True)
    assert key["owner"] == owner and key["liquidity"] == 11
    assert key["fee_growth_inside0_last"] == u256_hex(2**255)
    tok = df.filter(pl.col("token_id") == 7).row(0, named=True)
    assert tok["found"] and tok["liquidity"] == 7 and tok["tokens_owed1"] == 5
    assert df.filter(pl.col("token_id") == 99)["found"].to_list() == [False]


def test_owner_code_is_cached(tmp_path: Path) -> None:
    fake = FakePositions()
    a, b = "0x" + "a1" * 20, "0x" + "c0" * 20
    chain_state.fetch_owner_code(fake, tmp_path, [a, b], 9)  # type: ignore[arg-type]
    path = chain_state.fetch_owner_code(fake, tmp_path, [a, b], 9)  # type: ignore[arg-type]
    df = pl.read_parquet(path).sort("address")
    assert df.rows() == [(a, False), (b, True)]
    assert fake.code_calls == [a, b]  # the second call read nothing


def test_state_targets_and_window_active() -> None:
    ts = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp()) * 1_000_000
    pos = pl.DataFrame(
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
                "first_block": 1,
                "first_ts_us": ts,
                "close_block": None,
                "close_ts_us": None,
            },
            {
                "position_id": "nft:2",
                "kind": "nft",
                "token_id": 2,
                "owner": NPM_ADDRESS,
                "tick_lower": -20,
                "tick_upper": 20,
                "lp": "0x" + "a1" * 20,
                "transferred": False,
                "first_block": 1,
                "first_ts_us": ts,
                "close_block": 3,
                "close_ts_us": ts,
            },
            {
                "position_id": "nft:3",
                "kind": "nft",
                "token_id": 3,
                "owner": NPM_ADDRESS,
                "tick_lower": -30,
                "tick_upper": 30,
                "lp": "0x" + "a1" * 20,
                "transferred": False,
                "first_block": 12,
                "first_ts_us": ts,
                "close_block": None,
                "close_ts_us": None,
            },
        ],
        schema=POSITION_SCHEMA,
    )

    def f(pid: str, tok: int, block: int, event: str, delta: int) -> dict[str, object]:
        return {
            "position_id": pid,
            "kind": "nft",
            "token_id": tok,
            "block_number": block,
            "log_index": 0,
            "pool_log_index": 0,
            "tx_hash": "0x",
            "ts_us": ts,
            "event": event,
            "liquidity_delta": delta,
            "amount0": 0,
            "amount1": 0,
        }

    flows = pl.DataFrame(
        [
            f("nft:1", 1, 1, "increase", 5),
            f("nft:2", 2, 1, "increase", 5),
            f("nft:2", 2, 3, "decrease", -5),
            f("nft:2", 2, 11, "collect", 0),
            f("nft:3", 3, 12, "increase", 5),
        ],
        schema=FLOW_SCHEMA,
    )
    data = LedgerData(pos, flows, {}, {1: "nft:1", 2: "nft:2", 3: "nft:3"})
    keys, tokens = chain_state.state_targets(data, 10, 10, include_new=False)
    assert tokens == [1, 2]  # 1 is open, 2 is closed but collects in the window; 3 is new
    assert keys == [(NPM_ADDRESS, -20, 20), (NPM_ADDRESS, -10, 10)]
    _, end_tokens = chain_state.state_targets(data, 20, 10, include_new=True)
    assert end_tokens == [1, 2, 3]
    assert chain_state.window_active_ids(data, 10) == ["nft:1", "nft:3"]
