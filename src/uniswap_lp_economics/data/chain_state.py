"""On-chain pool state for sub-project 3 (spec D2-D4), read with Multicall3.

uint256 values (fee growth) are stored as 64-char hex strings: they do not fit Int128.
"""

from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.config import POOL_ADDRESS
from uniswap_lp_economics.io import u256_hex, write_exact
from uniswap_lp_economics.rpc import (
    FEE_GROWTH_GLOBAL0_CALL,
    FEE_GROWTH_GLOBAL1_CALL,
    RpcClient,
    decode_tick_fees,
    decode_ticks,
    decode_uint,
    ticks_call,
)
from uniswap_lp_economics.snapshot import batched

CHAIN_DIR = "chain_state"
SNAPSHOT_FEES = "snapshot_fees.parquet"
SAMPLE_FEES = "sample_fees.parquet"
FEE_SCHEMA: dict[str, Any] = {
    "block": pl.Int64,
    "kind": pl.String,
    "tick": pl.Int64,
    "fee_growth0": pl.String,
    "fee_growth1": pl.String,
}


def read_fee_state(client: RpcClient, block: int, ticks: list[int]) -> pl.DataFrame:
    """feeGrowthGlobal0/1X128 and each tick's feeGrowthOutside0/1X128 at `block`."""
    calls = [(POOL_ADDRESS, FEE_GROWTH_GLOBAL0_CALL), (POOL_ADDRESS, FEE_GROWTH_GLOBAL1_CALL)]
    calls += [(POOL_ADDRESS, ticks_call(t)) for t in ticks]
    results = batched(client, calls, block)
    g0, g1 = (decode_uint(r) for r in results[:2] if r is not None)
    rows: list[dict[str, Any]] = [
        {
            "block": block,
            "kind": "global",
            "tick": None,
            "fee_growth0": u256_hex(g0),
            "fee_growth1": u256_hex(g1),
        }
    ]
    for t, result in zip(ticks, results[2:], strict=True):
        assert result is not None
        _, _, initialized = decode_ticks(result)
        if not initialized:
            raise RuntimeError(f"tick {t} is not initialized at block {block}")
        o0, o1 = decode_tick_fees(result)
        rows.append(
            {
                "block": block,
                "kind": "tick",
                "tick": t,
                "fee_growth0": u256_hex(o0),
                "fee_growth1": u256_hex(o1),
            }
        )
    return pl.DataFrame(rows, schema=FEE_SCHEMA)


def fetch_snapshot_fees(client: RpcClient, raw_dir: Path, block: int, ticks: list[int]) -> Path:
    out = raw_dir / CHAIN_DIR / SNAPSHOT_FEES
    out.parent.mkdir(parents=True, exist_ok=True)
    df = read_fee_state(client, block, sorted(ticks))
    write_exact(df, out)
    print(f"snapshot fee state at block {block}: {len(ticks)} ticks")
    return out


def fetch_sample_fees(client: RpcClient, raw_dir: Path, sample_ticks: pl.DataFrame) -> Path:
    """Fee state at every sample block, for the ticks C3 already sampled there (check L2)."""
    out = raw_dir / CHAIN_DIR / SAMPLE_FEES
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    groups = sample_ticks.partition_by("block", as_dict=True, maintain_order=True)
    for i, ((block,), g) in enumerate(sorted(groups.items())):
        frames.append(read_fee_state(client, int(block), sorted(g["tick"].to_list())))
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(groups)} sample blocks")
    write_exact(pl.concat(frames), out)
    print(f"sample fee state: {len(groups)} blocks")
    return out
