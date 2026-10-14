from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics import abi
from uniswap_lp_economics.data import chain_state
from uniswap_lp_economics.io import hex_u256
from uniswap_lp_economics.rpc import FEE_GROWTH_GLOBAL0_CALL, FEE_GROWTH_GLOBAL1_CALL


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
