"""On-chain pool state for sub-project 3 (spec D2-D4), read with Multicall3.

uint256 values (fee growth) are stored as 64-char hex strings: they do not fit Int128.
"""

from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.config import NPM_ADDRESS, POOL_ADDRESS
from uniswap_lp_economics.io import u256_hex, write_exact
from uniswap_lp_economics.lp.positions import LedgerData, liquidity_at
from uniswap_lp_economics.rpc import (
    FEE_GROWTH_GLOBAL0_CALL,
    FEE_GROWTH_GLOBAL1_CALL,
    RpcClient,
    decode_npm_position,
    decode_pool_position,
    decode_tick_fees,
    decode_ticks,
    decode_uint,
    npm_positions_call,
    pool_positions_call,
    position_key,
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


START_POSITIONS = "start_positions.parquet"
END_POSITIONS = "end_positions.parquet"
OWNER_CODE = "owner_code.parquet"
POSITION_STATE_SCHEMA: dict[str, Any] = {
    "block": pl.Int64,
    "kind": pl.String,
    "owner": pl.String,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "token_id": pl.Int64,
    "found": pl.Boolean,
    "liquidity": pl.Int128,
    "fee_growth_inside0_last": pl.String,
    "fee_growth_inside1_last": pl.String,
    "tokens_owed0": pl.Int128,
    "tokens_owed1": pl.Int128,
}
_I128_MAX = 2**127 - 1


def _owed(value: int) -> int:
    if value > _I128_MAX:
        raise ValueError(f"tokens owed {value} does not fit Int128")
    return value


def read_position_state(
    client: RpcClient, block: int, keys: list[tuple[str, int, int]], tokens: list[int]
) -> pl.DataFrame:
    """pool.positions(key) for each (owner, lower, upper) and NPM.positions(tokenId) at `block`.

    A token whose call reverts (burned NFT) comes back with found = False."""
    calls = [(POOL_ADDRESS, pool_positions_call(position_key(*k))) for k in keys]
    calls += [(NPM_ADDRESS, npm_positions_call(t)) for t in tokens]
    results = batched(client, calls, block, allow_failure=True)
    rows: list[dict[str, Any]] = []
    for (owner, lo, hi), res in zip(keys, results[: len(keys)], strict=True):
        if res is None:
            raise RuntimeError(f"pool.positions failed for {owner} {lo} {hi} at block {block}")
        d = decode_pool_position(res)
        rows.append(
            {
                "block": block,
                "kind": "pool_key",
                "owner": owner,
                "tick_lower": lo,
                "tick_upper": hi,
                "token_id": None,
                "found": True,
                "liquidity": d["liquidity"],
                "fee_growth_inside0_last": u256_hex(d["fee_growth_inside0_last"]),
                "fee_growth_inside1_last": u256_hex(d["fee_growth_inside1_last"]),
                "tokens_owed0": _owed(d["tokens_owed0"]),
                "tokens_owed1": _owed(d["tokens_owed1"]),
            }
        )
    for token, res in zip(tokens, results[len(keys) :], strict=True):
        if res is None:
            rows.append({"block": block, "kind": "npm_token", "token_id": token, "found": False})
            continue
        n = decode_npm_position(res)
        rows.append(
            {
                "block": block,
                "kind": "npm_token",
                "owner": NPM_ADDRESS,
                "tick_lower": n["tick_lower"],
                "tick_upper": n["tick_upper"],
                "token_id": token,
                "found": True,
                "liquidity": n["liquidity"],
                "fee_growth_inside0_last": u256_hex(n["fee_growth_inside0_last"]),
                "fee_growth_inside1_last": u256_hex(n["fee_growth_inside1_last"]),
                "tokens_owed0": _owed(n["tokens_owed0"]),
                "tokens_owed1": _owed(n["tokens_owed1"]),
            }
        )
    return pl.DataFrame(rows, schema=POSITION_STATE_SCHEMA)


def state_targets(
    data: LedgerData, block: int, snapshot_block: int, include_new: bool
) -> tuple[list[tuple[str, int, int]], list[int]]:
    """Pool keys and NPM tokens whose on-chain state the ledger needs at `block`: liquidity > 0
    there, or any flow after the snapshot.

    Keys always cover every such position, new ones included: a key can hold an earlier episode's
    (or another token's) owed tokens from before the snapshot, and the contract carries them into
    the new position. Token ids are never reused, so without include_new only tokens that existed
    by the snapshot are read."""
    open_ids = set(liquidity_at(data, block)["position_id"].to_list())
    touched = set(
        data.flows.filter(pl.col("block_number") > snapshot_block)["position_id"].to_list()
    )
    pos = data.positions.filter(pl.col("position_id").is_in(list(open_ids | touched)))
    keys = sorted(
        {(o, lo, hi) for o, lo, hi in pos.select("owner", "tick_lower", "tick_upper").iter_rows()},
        key=lambda k: (k[0], k[1], k[2]),
    )
    if not include_new:
        pos = pos.filter(pl.col("first_block") <= snapshot_block)
    tokens = sorted(int(t) for t in pos["token_id"].drop_nulls().to_list())
    return keys, tokens


def window_active_ids(data: LedgerData, snapshot_block: int) -> list[str]:
    """Positions holding liquidity at some moment of the window (spec section 4)."""
    open_at_start = set(liquidity_at(data, snapshot_block)["position_id"].to_list())
    added = set(
        data.flows.filter(
            (pl.col("block_number") > snapshot_block) & (pl.col("liquidity_delta") > 0)
        )["position_id"].to_list()
    )
    return sorted(open_at_start | added)


def fetch_position_state(
    client: RpcClient,
    raw_dir: Path,
    block: int,
    keys: list[tuple[str, int, int]],
    tokens: list[int],
    name: str,
) -> Path:
    out = raw_dir / CHAIN_DIR / name
    out.parent.mkdir(parents=True, exist_ok=True)
    df = read_position_state(client, block, keys, tokens)
    write_exact(df, out)
    print(f"{name}: {len(keys)} pool keys, {len(tokens)} NFT positions at block {block}")
    return out


EIP7702_PREFIX = "ef0100"
EIP7702_CODE_HEX_LEN = 46  # 23 bytes: the 3-byte prefix and a 20-byte delegate address


def parse_code(code: str) -> tuple[bool, str | None]:
    """`(has_code, eip7702_delegate)` for the result of `eth_getCode`.

    Since EIP-7702 a delegated EOA has code `0xef0100` + the 20-byte delegate address (23 bytes).
    It is a user wallet, so it has no contract code; the delegate address is returned instead.
    """
    hex_code = code.removeprefix("0x").removeprefix("0X").lower()
    if not hex_code:
        return False, None
    if hex_code.startswith(EIP7702_PREFIX) and len(hex_code) == EIP7702_CODE_HEX_LEN:
        return False, "0x" + hex_code[len(EIP7702_PREFIX) :]
    return True, None


def fetch_owner_code(client: RpcClient, raw_dir: Path, addresses: list[str], block: int) -> Path:
    """Whether each address has contract code at `block`; cached, so reruns read only new ones.

    `has_code` is False for EOAs, including EIP-7702 delegated ones, whose delegate is recorded in
    `eip7702_delegate`. A cache written before that column existed is read again in full.
    """
    out = raw_dir / CHAIN_DIR / OWNER_CODE
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = {"address": pl.String, "has_code": pl.Boolean, "eip7702_delegate": pl.String}
    known = pl.DataFrame(schema=schema)
    if out.exists():
        cached = pl.read_parquet(out)
        if "eip7702_delegate" in cached.columns:
            known = cached.select(list(schema))
        else:
            print("owner_code cache has no eip7702_delegate column: reading every address again")
    done = set(known["address"].to_list())
    todo = [a for a in sorted(set(addresses)) if a not in done]
    rows = []
    for i, a in enumerate(todo):
        has_code, delegate = parse_code(client.get_code(a, block))
        rows.append({"address": a, "has_code": has_code, "eip7702_delegate": delegate})
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(todo)} owner addresses")
    new = pl.DataFrame(rows, schema=schema)
    write_exact(pl.concat([known, new]), out)
    return out
