"""Position identity from the full history (spec section 4).

NFT positions: one per token, each NPM IncreaseLiquidity / DecreaseLiquidity / Collect matched to
the pool Mint / Burn / (poke Burn +) Collect of the same transaction that the position manager
emitted just before it. Direct positions: keyed like the contract, (owner, lower, upper), and split
into a new position each time the key's liquidity returns to zero. Nothing is dropped silently:
an unmatched event raises with its block and log index.
"""

from dataclasses import dataclass, field
from typing import Any

import polars as pl

from uniswap_lp_economics.config import NPM_ADDRESS

ZERO_ADDRESS = "0x" + "00" * 20
FLOW_SCHEMA: dict[str, Any] = {
    "position_id": pl.String,
    "kind": pl.String,
    "token_id": pl.Int64,
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "pool_log_index": pl.Int64,
    "tx_hash": pl.String,
    "ts_us": pl.Int64,
    "event": pl.String,
    "liquidity_delta": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
}
POSITION_SCHEMA: dict[str, Any] = {
    "position_id": pl.String,
    "kind": pl.String,
    "token_id": pl.Int64,
    "owner": pl.String,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "lp": pl.String,
    "transferred": pl.Boolean,
    "first_block": pl.Int64,
    "first_ts_us": pl.Int64,
    "close_block": pl.Int64,
    "close_ts_us": pl.Int64,
}


@dataclass
class _Position:
    position_id: str
    kind: str
    token_id: int | None
    owner: str
    tick_lower: int
    tick_upper: int
    first_block: int
    first_ts_us: int
    liquidity: int = 0
    transferred: bool = False
    close_block: int | None = None
    close_log: int | None = None
    close_ts_us: int | None = None


@dataclass
class LedgerData:
    positions: pl.DataFrame
    flows: pl.DataFrame
    pool_event_position: dict[tuple[int, int], str] = field(default_factory=dict)
    token_position: dict[int, str] = field(default_factory=dict)
    # (block_number, log_index) of zero collects on direct keys that were never minted: the pool
    # contract emits Collect(0, 0) for any key, so these are no-ops with no position and no flow.
    noop_collects: set[tuple[int, int]] = field(default_factory=set)
    # (token_id, block_number, log_index, d0, d1) of NPM collects whose pool Collect paid less than
    # the NPM event's requested amounts (d = NPM - pool); the flow keeps the NPM amounts.
    collect_shortfalls: list[tuple[int, int, int, int, int]] = field(default_factory=list)


def _rows(df: pl.DataFrame, source: str, columns: list[str]) -> list[dict[str, Any]]:
    present = [c for c in columns if c in df.columns]
    out = df.select(*present, ts_us=pl.col("block_timestamp").dt.epoch("us")).with_columns(
        src=pl.lit(source)
    )
    return out.to_dicts()


def build_positions(
    pool_events: pl.DataFrame, npm_events: pl.DataFrame, npm_address: str = NPM_ADDRESS
) -> LedgerData:
    pool_cols = [
        "block_number",
        "log_index",
        "tx_hash",
        "event",
        "owner",
        "tick_lower",
        "tick_upper",
        "amount",
        "amount0",
        "amount1",
    ]
    npm_cols = [
        "block_number",
        "log_index",
        "tx_hash",
        "event",
        "token_id",
        "liquidity",
        "amount0",
        "amount1",
        "from_owner",
        "to_owner",
    ]
    pool = pool_events.filter(pl.col("event").is_in(["mint", "burn", "collect"]))
    merged = sorted(
        _rows(pool, "pool", pool_cols) + _rows(npm_events, "npm", npm_cols),
        key=lambda r: (r["block_number"], r["log_index"]),
    )

    positions: dict[str, _Position] = {}
    flows: list[dict[str, Any]] = []
    direct_current: dict[tuple[str, int, int], _Position] = {}
    episodes: dict[tuple[str, int, int], int] = {}
    tokens: dict[int, _Position] = {}
    owners: dict[int, list[tuple[int, int, str]]] = {}
    pool_event_position: dict[tuple[int, int], str] = {}
    noop_collects: set[tuple[int, int]] = set()
    collect_shortfalls: list[tuple[int, int, int, int, int]] = []
    pending: list[dict[str, Any]] = []
    current_tx: str | None = None

    def where(r: dict[str, Any]) -> str:
        return f"block {r['block_number']} log {r['log_index']}"

    def flush_tx() -> None:
        if pending:
            r = pending[0]
            raise ValueError(
                f"pool {r['event']} at {where(r)} owned by the position manager has no matching "
                "NonfungiblePositionManager event"
            )

    def take(pred: Any) -> dict[str, Any] | None:
        for i, cand in enumerate(pending):
            if pred(cand):
                return pending.pop(i)
        return None

    def flow(pos: _Position, r: dict[str, Any], event: str, delta: int, pool_log: int) -> None:
        flows.append(
            {
                "position_id": pos.position_id,
                "kind": pos.kind,
                "token_id": pos.token_id,
                "block_number": r["block_number"],
                "log_index": r["log_index"],
                "pool_log_index": pool_log,
                "tx_hash": r["tx_hash"],
                "ts_us": r["ts_us"],
                "event": event,
                "liquidity_delta": delta,
                "amount0": r["amount0"] or 0,
                "amount1": r["amount1"] or 0,
            }
        )

    def close_if_empty(pos: _Position, r: dict[str, Any]) -> None:
        if pos.liquidity == 0:
            pos.close_block, pos.close_log, pos.close_ts_us = (
                r["block_number"],
                r["log_index"],
                r["ts_us"],
            )

    def same_range(pos: _Position) -> Any:
        return lambda c: (c["tick_lower"], c["tick_upper"]) == (pos.tick_lower, pos.tick_upper)

    def direct(r: dict[str, Any]) -> None:
        key = (r["owner"], r["tick_lower"], r["tick_upper"])
        pos = direct_current.get(key)
        if r["event"] == "mint":
            if pos is None or pos.liquidity == 0:
                k = episodes.get(key, 0)
                episodes[key] = k + 1
                pos = _Position(
                    f"direct:{key[0]}:{key[1]}:{key[2]}:{k}",
                    "direct",
                    None,
                    key[0],
                    key[1],
                    key[2],
                    r["block_number"],
                    r["ts_us"],
                )
                positions[pos.position_id] = pos
                direct_current[key] = pos
            pos.liquidity += r["amount"]
            flow(pos, r, "mint", r["amount"], r["log_index"])
        elif pos is None:
            if r["event"] == "collect" and not r["amount0"] and not r["amount1"]:
                noop_collects.add((r["block_number"], r["log_index"]))
                return
            raise ValueError(f"pool {r['event']} at {where(r)} for a position never minted")
        elif r["event"] == "burn":
            if r["amount"] > pos.liquidity:
                raise ValueError(f"burn at {where(r)} exceeds the position's liquidity")
            pos.liquidity -= r["amount"]
            flow(pos, r, "burn" if r["amount"] else "poke", -r["amount"], r["log_index"])
            if r["amount"]:
                close_if_empty(pos, r)
        else:
            flow(pos, r, "collect", 0, r["log_index"])
        pool_event_position[(r["block_number"], r["log_index"])] = pos.position_id

    def nft(r: dict[str, Any]) -> None:
        tid = r["token_id"]
        if r["event"] == "transfer":
            owners.setdefault(tid, []).append((r["block_number"], r["log_index"], r["to_owner"]))
            pos = tokens.get(tid)
            moved = r["from_owner"] != ZERO_ADDRESS and r["to_owner"] != ZERO_ADDRESS
            if pos is not None and pos.liquidity > 0 and moved:
                pos.transferred = True
            return
        pos = tokens.get(tid)
        if r["event"] == "increase":
            m = take(lambda c: c["event"] == "mint" and c["amount"] == r["liquidity"])
            if m is None:
                if pos is not None:
                    raise ValueError(
                        f"IncreaseLiquidity of token {tid} at {where(r)} has no pool Mint"
                    )
                return  # a token of another pool
            if pos is None:
                pos = _Position(
                    f"nft:{tid}",
                    "nft",
                    tid,
                    npm_address,
                    m["tick_lower"],
                    m["tick_upper"],
                    r["block_number"],
                    r["ts_us"],
                )
                positions[pos.position_id] = pos
                tokens[tid] = pos
            elif (pos.tick_lower, pos.tick_upper) != (m["tick_lower"], m["tick_upper"]):
                raise ValueError(f"token {tid} at {where(r)} matched a Mint of another range")
            pos.liquidity += r["liquidity"]
            pos.close_block = pos.close_log = pos.close_ts_us = None
            flow(pos, r, "increase", r["liquidity"], m["log_index"])
            pool_event_position[(m["block_number"], m["log_index"])] = pos.position_id
            return
        if pos is None:
            return  # a token of another pool
        if r["event"] == "decrease":
            m = take(
                lambda c: (
                    c["event"] == "burn" and c["amount"] == r["liquidity"] and same_range(pos)(c)
                )
            )
            if m is None:
                raise ValueError(f"DecreaseLiquidity of token {tid} at {where(r)} has no pool Burn")
            pos.liquidity -= r["liquidity"]
            flow(pos, r, "decrease", -r["liquidity"], m["log_index"])
            pool_event_position[(m["block_number"], m["log_index"])] = pos.position_id
            close_if_empty(pos, r)
            return
        # npm_collect: a poke Burn(0) first when the token still holds liquidity
        if pos.liquidity > 0:
            poke = take(lambda c: c["event"] == "burn" and c["amount"] == 0 and same_range(pos)(c))
            if poke is None:
                raise ValueError(f"Collect of token {tid} at {where(r)} has no poke Burn")
            pool_event_position[(poke["block_number"], poke["log_index"])] = pos.position_id
        # The NPM event carries the requested amounts min(amountMax, token owed); the pool pays
        # min(requested, the key's owed), which may be a raw unit or so lower.
        c = take(
            lambda c: (
                c["event"] == "collect"
                and same_range(pos)(c)
                and c["amount0"] <= r["amount0"]
                and c["amount1"] <= r["amount1"]
            )
        )
        if c is None:
            raise ValueError(f"Collect of token {tid} at {where(r)} has no pool Collect")
        d0, d1 = r["amount0"] - c["amount0"], r["amount1"] - c["amount1"]
        if d0 or d1:
            collect_shortfalls.append((tid, r["block_number"], r["log_index"], d0, d1))
        flow(pos, r, "collect", 0, c["log_index"])
        pool_event_position[(c["block_number"], c["log_index"])] = pos.position_id

    for r in merged:
        if r["tx_hash"] != current_tx:
            flush_tx()
            current_tx = r["tx_hash"]
        if r["src"] == "pool":
            if r["owner"] == npm_address:
                pending.append(r)
            else:
                direct(r)
        else:
            nft(r)
    flush_tx()

    rows = []
    for pos in positions.values():
        lp = pos.owner
        if pos.kind == "nft":
            ref = (pos.close_block, pos.close_log) if pos.close_block is not None else None
            history = owners.get(pos.token_id or -1, [])
            before = [h for h in history if ref is None or (h[0], h[1]) <= ref]
            lp = before[-1][2] if before else ZERO_ADDRESS
        rows.append(
            {
                "position_id": pos.position_id,
                "kind": pos.kind,
                "token_id": pos.token_id,
                "owner": pos.owner,
                "tick_lower": pos.tick_lower,
                "tick_upper": pos.tick_upper,
                "lp": lp,
                "transferred": pos.transferred,
                "first_block": pos.first_block,
                "first_ts_us": pos.first_ts_us,
                "close_block": pos.close_block,
                "close_ts_us": pos.close_ts_us,
            }
        )
    return LedgerData(
        positions=pl.DataFrame(rows, schema=POSITION_SCHEMA),
        flows=pl.DataFrame(flows, schema=FLOW_SCHEMA),
        pool_event_position=pool_event_position,
        token_position={tid: pos.position_id for tid, pos in tokens.items()},
        noop_collects=noop_collects,
        collect_shortfalls=collect_shortfalls,
    )


def liquidity_at(data: LedgerData, block: int) -> pl.DataFrame:
    """Positions with liquidity > 0 after every event of `block`."""
    liq = (
        data.flows.filter(pl.col("block_number") <= block)
        .group_by("position_id")
        .agg(liquidity=pl.col("liquidity_delta").sum())
        .filter(pl.col("liquidity") > 0)
    )
    return (
        data.positions.select("position_id", "tick_lower", "tick_upper")
        .join(liq, on="position_id", how="inner")
        .sort("position_id")
    )
