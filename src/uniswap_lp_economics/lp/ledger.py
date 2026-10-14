"""Contract mirror and attribution per position during the window replay (spec section 5).

The contract mirror holds what the chain stores for each pool position key and each NPM token,
updated only by events with the contract's arithmetic (check L3 compares it with the chain).
The attribution layer holds what each position earned inside the window: raw fees checkpoint at
the mirror's events and at the window boundaries (so their floors match the contract's); USD fees
and LVR also checkpoint at each new UTC day (plan Ruling 9).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import polars as pl

from uniswap_lp_economics.config import NPM_ADDRESS
from uniswap_lp_economics.io import hex_u256
from uniswap_lp_economics.lp.engine import EngineRow
from uniswap_lp_economics.lp.positions import LedgerData, liquidity_at
from uniswap_lp_economics.lp.state import Q128, PoolState, sub256

U128 = 2**128
ACCOUNT_SCHEMA: dict[str, Any] = {
    "position_id": pl.String,
    "liquidity_start": pl.Int128,
    "liquidity_end": pl.Int128,
    "active": pl.Boolean,
    "carried_owed": pl.Boolean,
    "fees_raw0": pl.Int128,
    "fees_raw1": pl.Int128,
    "fee_usd": pl.Float64,
    "lvr_0": pl.Float64,
    "lvr_12": pl.Float64,
    "owed_end0": pl.Int128,
    "owed_end1": pl.Int128,
    "pending_end0": pl.Int128,
    "pending_end1": pl.Int128,
}
DAY_SCHEMA: dict[str, Any] = {
    "position_id": pl.String,
    "day": pl.Date,
    "fee_usd": pl.Float64,
    "lvr_0": pl.Float64,
    "lvr_12": pl.Float64,
}


def accrue(liquidity: int, inside: int, last: int) -> int:
    """uint128(mulDiv(inside - last, liquidity, 2^128)) with uint256 wrap-around."""
    return sub256(inside, last) * liquidity // Q128 % U128


@dataclass
class KeyMirror:
    liquidity: int
    last0: int
    last1: int
    owed0: int
    owed1: int
    # Float accumulators' inside value at the last update. NPM events read the pool key's stored
    # values (as NonfungiblePositionManager reads pool.positions), because the pool Burn just
    # before them may have cleared the ticks.
    last_f: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])


@dataclass
class Account:
    position_id: str
    kind: str
    tick_lower: int
    tick_upper: int
    mirror: KeyMirror  # NPM token state, or the shared pool-key state of a direct position
    att0: int
    att1: int
    att_f: list[float]
    liquidity: int = 0
    liquidity_start: int = 0
    carried_owed: bool = False
    active: bool = False
    fees0: int = 0
    fees1: int = 0
    fees_f: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    days: dict[date, list[float]] = field(default_factory=dict)
    pending0: int = 0
    pending1: int = 0


def _mirror(row: dict[str, Any]) -> KeyMirror:
    return KeyMirror(
        int(row["liquidity"]),
        hex_u256(row["fee_growth_inside0_last"]),
        hex_u256(row["fee_growth_inside1_last"]),
        int(row["tokens_owed0"]),
        int(row["tokens_owed1"]),
    )


def _accrue_mirror(m: KeyMirror, inside: tuple[int, int, list[float]]) -> None:
    m.owed0 += accrue(m.liquidity, inside[0], m.last0)
    m.owed1 += accrue(m.liquidity, inside[1], m.last1)
    m.last0, m.last1, m.last_f = inside[0], inside[1], list(inside[2])


def _has_ticks(state: PoolState, lo: int, hi: int) -> bool:
    return lo in state.acc.foutside and hi in state.acc.foutside


class Ledger:
    def __init__(
        self,
        data: LedgerData,
        start_state: pl.DataFrame,
        snapshot_block: int,
        npm_address: str = NPM_ADDRESS,
    ) -> None:
        self.data = data
        self.npm = npm_address
        self.snapshot_block = snapshot_block
        self.keys: dict[tuple[str, int, int], KeyMirror] = {}
        self.accounts: dict[str, Account] = {}
        self.current_direct: dict[tuple[str, int, int], str] = {}
        self.start_mismatches: list[dict[str, Any]] = []
        self.day: date | None = None
        self._start_rows = start_state
        self._pos = {r["position_id"]: r for r in data.positions.iter_rows(named=True)}
        self._start_liq: dict[str, int] = dict(
            liquidity_at(data, snapshot_block).select("position_id", "liquidity").iter_rows()
        )
        self._touched = set(
            data.flows.filter(pl.col("block_number") > snapshot_block)["position_id"].to_list()
        )

    # --- hooks ---------------------------------------------------------------------------

    def start(self, state: PoolState) -> None:
        found = self._start_rows.filter(pl.col("found"))
        for r in found.filter(pl.col("kind") == "pool_key").iter_rows(named=True):
            km = _mirror(r)
            lo, hi = r["tick_lower"], r["tick_upper"]
            if _has_ticks(state, lo, hi):
                km.last_f = state.inside(lo, hi)[2]
            self.keys[(r["owner"], lo, hi)] = km
        tokens = {
            r["token_id"]: r
            for r in found.filter(pl.col("kind") == "npm_token").iter_rows(named=True)
        }
        for pid, p in self._pos.items():
            if p["first_block"] > self.snapshot_block:
                continue
            liq = self._start_liq.get(pid, 0)
            if liq == 0 and pid not in self._touched:
                continue
            key = (p["owner"], p["tick_lower"], p["tick_upper"])
            if p["kind"] == "nft":
                row = tokens.get(p["token_id"])
                mirror = None if row is None else _mirror(row)
            else:
                mirror = self.keys.get(key)
                self.current_direct[key] = pid
            if mirror is None:
                self.start_mismatches.append({"position_id": pid, "issue": "no start state"})
                continue
            if mirror.liquidity != liq:
                self.start_mismatches.append(
                    {"position_id": pid, "ledger": liq, "onchain": mirror.liquidity}
                )
            if _has_ticks(state, p["tick_lower"], p["tick_upper"]):
                i0, i1, f = state.inside(p["tick_lower"], p["tick_upper"])
            else:  # no liquidity on the range now: checkpoints are reset at the next increase
                i0, i1, f = mirror.last0, mirror.last1, [0.0, 0.0, 0.0]
            self.accounts[pid] = Account(
                pid,
                p["kind"],
                p["tick_lower"],
                p["tick_upper"],
                mirror,
                i0,
                i1,
                list(f),
                liquidity=liq,
                liquidity_start=liq,
                carried_owed=True,
                active=liq > 0,
            )

    def on_pool_event(self, row: EngineRow, state: PoolState) -> None:
        assert row.owner is not None and row.tick_lower is not None and row.tick_upper is not None
        key = (row.owner, row.tick_lower, row.tick_upper)
        where = f"{row.event} at block {row.block_number} log {row.log_index}"
        km = self.keys.get(key)
        amount = int(row.amount or 0)
        a0, a1 = int(row.amount0 or 0), int(row.amount1 or 0)
        # Collect needs no fee growth (and its ticks may already be cleared).
        inside = state.inside(*key[1:]) if row.event in ("mint", "burn") else None
        if inside is not None and row.event == "mint" and km is None:
            km = KeyMirror(0, inside[0], inside[1], 0, 0, list(inside[2]))
            self.keys[key] = km
        elif km is None:
            raise ValueError(f"{where} for a pool key with no state")
        elif inside is not None:
            _accrue_mirror(km, inside)
        if row.owner != self.npm:
            pid = self.data.pool_event_position[(row.block_number, row.log_index)]
            acc = self.accounts.get(pid)
            if acc is None:
                if inside is None or row.event != "mint":
                    raise ValueError(f"{where} before its position has any state")
                acc = self._new_account(pid, inside, km, carried=(km.owed0, km.owed1) != (0, 0))
                self.current_direct[key] = pid
            if inside is not None:
                self._attribute(acc, inside, raw=True)
                acc.liquidity += amount if row.event == "mint" else -amount
                acc.active = acc.active or acc.liquidity > 0
        if row.event == "mint":
            km.liquidity += amount
        elif row.event == "burn":
            km.liquidity -= amount
            km.owed0 += a0
            km.owed1 += a1
        else:
            km.owed0 -= a0
            km.owed1 -= a1

    def on_npm_event(self, row: EngineRow, state: PoolState) -> None:
        pid = self.data.token_position.get(int(row.token_id or -1))
        if pid is None:
            return  # a token of another pool
        p = self._pos[pid]
        km = self.keys.get((self.npm, p["tick_lower"], p["tick_upper"]))
        if km is None:
            raise ValueError(
                f"{row.event} of token {row.token_id} at block {row.block_number} has no pool key"
            )
        # NonfungiblePositionManager reads pool.positions(key) right after the pool call.
        inside = (km.last0, km.last1, list(km.last_f))
        acc = self.accounts.get(pid)
        if acc is None:
            if row.event != "increase":
                raise ValueError(
                    f"{row.event} of token {row.token_id} at block {row.block_number} "
                    "before the token has any state"
                )
            mirror = KeyMirror(0, inside[0], inside[1], 0, 0, list(inside[2]))
            acc = self._new_account(pid, inside, mirror, False)
        m = acc.mirror
        liquidity = int(row.liquidity or 0)
        a0, a1 = int(row.amount0 or 0), int(row.amount1 or 0)
        if row.event == "increase":
            _accrue_mirror(m, inside)
            self._attribute(acc, inside, raw=True)
            m.liquidity += liquidity
            acc.liquidity += liquidity
        elif row.event == "decrease":
            _accrue_mirror(m, inside)
            m.owed0 += a0
            m.owed1 += a1
            self._attribute(acc, inside, raw=True)
            m.liquidity -= liquidity
            acc.liquidity -= liquidity
        elif row.event == "npm_collect":
            if m.liquidity > 0:  # NPM pokes the pool first only when the token holds liquidity
                _accrue_mirror(m, inside)
                self._attribute(acc, inside, raw=True)
            m.owed0 -= a0
            m.owed1 -= a1
        acc.active = acc.active or acc.liquidity > 0

    def new_day(self, day: date, state: PoolState) -> None:
        if self.day is not None:
            for acc in self.accounts.values():
                if acc.liquidity > 0:
                    self._attribute(acc, state.inside(acc.tick_lower, acc.tick_upper), raw=False)
        self.day = day

    def finish(self, state: PoolState) -> None:
        for acc in self.accounts.values():
            if acc.liquidity <= 0:
                continue
            inside = state.inside(acc.tick_lower, acc.tick_upper)
            self._attribute(acc, inside, raw=True)
            acc.pending0 = accrue(acc.mirror.liquidity, inside[0], acc.mirror.last0)
            acc.pending1 = accrue(acc.mirror.liquidity, inside[1], acc.mirror.last1)

    # --- helpers --------------------------------------------------------------------------

    def _new_account(
        self, pid: str, inside: tuple[int, int, list[float]], mirror: KeyMirror, carried: bool
    ) -> Account:
        p = self._pos[pid]
        acc = Account(
            pid,
            p["kind"],
            p["tick_lower"],
            p["tick_upper"],
            mirror,
            inside[0],
            inside[1],
            list(inside[2]),
            carried_owed=carried,
        )
        self.accounts[pid] = acc
        return acc

    def _attribute(self, acc: Account, inside: tuple[int, int, list[float]], raw: bool) -> None:
        i0, i1, f = inside
        if raw:
            acc.fees0 += sub256(i0, acc.att0) * acc.liquidity // Q128
            acc.fees1 += sub256(i1, acc.att1) * acc.liquidity // Q128
            acc.att0, acc.att1 = i0, i1
        bucket = acc.days.setdefault(self.day, [0.0, 0.0, 0.0]) if self.day else None
        for k in range(3):
            d = acc.liquidity * (f[k] - acc.att_f[k])
            acc.fees_f[k] += d
            if bucket is not None:
                bucket[k] += d
        acc.att_f = list(f)

    def token_mirror(self, token_id: int) -> KeyMirror | None:
        pid = self.data.token_position.get(token_id)
        acc = None if pid is None else self.accounts.get(pid)
        return None if acc is None else acc.mirror

    def accounts_frame(self) -> pl.DataFrame:
        rows = []
        for acc in self.accounts.values():
            p = self._pos[acc.position_id]
            key = (p["owner"], p["tick_lower"], p["tick_upper"])
            current = acc.kind == "nft" or self.current_direct.get(key) == acc.position_id
            rows.append(
                {
                    "position_id": acc.position_id,
                    "liquidity_start": acc.liquidity_start,
                    "liquidity_end": acc.liquidity,
                    "active": acc.active,
                    "carried_owed": acc.carried_owed,
                    "fees_raw0": acc.fees0,
                    "fees_raw1": acc.fees1,
                    "fee_usd": acc.fees_f[0],
                    "lvr_0": acc.fees_f[1],
                    "lvr_12": acc.fees_f[2],
                    "owed_end0": acc.mirror.owed0 if current else 0,
                    "owed_end1": acc.mirror.owed1 if current else 0,
                    "pending_end0": acc.pending0,
                    "pending_end1": acc.pending1,
                }
            )
        return pl.DataFrame(rows, schema=ACCOUNT_SCHEMA)

    def days_frame(self) -> pl.DataFrame:
        rows = [
            {
                "position_id": acc.position_id,
                "day": d,
                "fee_usd": v[0],
                "lvr_0": v[1],
                "lvr_12": v[2],
            }
            for acc in self.accounts.values()
            for d, v in sorted(acc.days.items())
        ]
        return pl.DataFrame(rows, schema=DAY_SCHEMA)
