"""Window replay of pool (and NPM) events through PoolState (spec section 5).

Every swap is reproduced bit-exactly (v3swap.reproduce_swap) and applied step by step to the fee
and LVR accumulators. A ledger, when given, sees every liquidity event in contract order.
"""

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, NamedTuple, Protocol

import polars as pl

from uniswap_lp_economics.lp.state import PoolState, StepRecord
from uniswap_lp_economics.v3swap import reproduce_swap


class EngineRow(NamedTuple):
    source: str
    block_number: int
    log_index: int
    ts_us: int
    tx_hash: str | None
    event: str
    owner: str | None
    tick_lower: int | None
    tick_upper: int | None
    amount: int | None
    amount0: int | None
    amount1: int | None
    sqrt_price_x96: int | None
    tick: int | None
    liquidity: int | None
    fee_protocol0_new: int | None
    fee_protocol1_new: int | None
    token_id: int | None
    paid0: int | None
    paid1: int | None


_DTYPES: dict[str, Any] = {
    "tx_hash": pl.String,
    "owner": pl.String,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "amount": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
    "sqrt_price_x96": pl.Int128,
    "tick": pl.Int64,
    "liquidity": pl.Int128,
    "fee_protocol0_new": pl.Int64,
    "fee_protocol1_new": pl.Int64,
    "token_id": pl.Int64,
    "paid0": pl.Int128,
    "paid1": pl.Int128,
}


def _prepare(df: pl.DataFrame, source: str) -> pl.DataFrame:
    cols = [
        pl.lit(source).alias("source"),
        pl.col("block_number").cast(pl.Int64),
        pl.col("log_index").cast(pl.Int64),
        pl.col("block_timestamp").dt.epoch("us").alias("ts_us"),
        pl.col("event"),
        *[
            (pl.col(c).cast(t) if c in df.columns else pl.lit(None, dtype=t)).alias(c)
            for c, t in _DTYPES.items()
        ],
    ]
    return df.select(cols).select(list(EngineRow._fields))


def iter_engine_rows(
    events: pl.DataFrame, npm_events: pl.DataFrame | None = None
) -> Iterator[EngineRow]:
    """Pool and NPM events merged in (block, log index) order; NPM transfers are dropped."""
    frames = [_prepare(events, "pool")]
    if npm_events is not None and npm_events.height:
        frames.append(_prepare(npm_events.filter(pl.col("event") != "transfer"), "npm"))
    for r in pl.concat(frames).sort("block_number", "log_index").iter_rows():
        yield EngineRow(*r)


@dataclass(frozen=True)
class SwapContext:
    p0: float
    p12: float | None
    flow_label: str
    ts_us: int


def contexts_from_aligned(aligned: pl.DataFrame) -> dict[tuple[int, int], SwapContext]:
    """Reference prices and flow labels per swap, from sub-project 2's aligned table."""
    out: dict[tuple[int, int], SwapContext] = {}
    for b, li, p0, p12, label, t0 in aligned.select(
        "block_number", "log_index", "p_cex_0", "p_cex_12", "flow_label", "t0_us"
    ).iter_rows():
        out[(b, li)] = SwapContext(float(p0), None if p12 is None else float(p12), label, t0)
    return out


class LedgerHooks(Protocol):
    def start(self, state: PoolState) -> None: ...
    def on_pool_event(self, row: EngineRow, state: PoolState) -> None: ...
    def on_npm_event(self, row: EngineRow, state: PoolState) -> None: ...
    def new_day(self, day: date, state: PoolState) -> None: ...
    def finish(self, state: PoolState) -> None: ...


STEP_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "step": pl.Int64,
    "zero_for_one": pl.Boolean,
    "flow_label": pl.String,
    "ts_us": pl.Int64,
    "liquidity": pl.Int128,
    "amount_in": pl.Int128,
    "amount_out": pl.Int128,
    "fee": pl.Int128,
    "protocol_fee": pl.Int128,
    "lp_fee": pl.Int128,
    "crossed_tick": pl.Int64,
    "fee_usd": pl.Float64,
    "lvr_0": pl.Float64,
    "lvr_12": pl.Float64,
    "lvr_12_missing": pl.Boolean,
    "accrued": pl.Boolean,
}


@dataclass
class WindowRun:
    steps: pl.DataFrame
    modes: dict[str, int]
    unmatched: list[dict[str, Any]]
    captures: dict[int, dict[str, Any]]
    zero_liquidity_steps: int
    null_12s_steps: int


def _day(ts_us: int) -> date:
    return datetime.fromtimestamp(ts_us / 1_000_000, UTC).date()


def _capture(state: PoolState, ticks: list[int]) -> dict[str, Any]:
    acc = state.acc
    return {
        "global0": acc.global0,
        "global1": acc.global1,
        "ticks": {t: (acc.outside0[t], acc.outside1[t]) for t in ticks if t in acc.outside0},
    }


def _need(row: EngineRow, name: str) -> int:
    value = getattr(row, name)
    if value is None:
        raise ValueError(
            f"{row.event} at block {row.block_number} log {row.log_index} has no {name}"
        )
    return int(value)


def replay_window(
    events: pl.DataFrame,
    state: PoolState,
    contexts: dict[tuple[int, int], SwapContext],
    capture: dict[int, list[int]] | None = None,
    ledger: LedgerHooks | None = None,
    npm_events: pl.DataFrame | None = None,
) -> WindowRun:
    """Replay the window from `state` (the snapshot state), advancing it in place."""
    pending = sorted(capture or {})
    captures: dict[int, dict[str, Any]] = {}
    records: list[StepRecord] = []
    modes: Counter[str] = Counter()
    unmatched: list[dict[str, Any]] = []
    current_day: date | None = None
    last_p0: float | None = None

    def flush(before_block: int | None) -> None:
        while pending and (before_block is None or pending[0] < before_block):
            b = pending.pop(0)
            captures[b] = _capture(state, (capture or {})[b])

    if ledger is not None:
        ledger.start(state)
    for row in iter_engine_rows(events, npm_events):
        flush(row.block_number)
        day = _day(row.ts_us)
        if day != current_day:
            if ledger is not None:
                ledger.new_day(day, state)
            current_day = day
        if row.source == "npm":
            if ledger is not None:
                ledger.on_npm_event(row, state)
            continue
        if row.event == "swap":
            ctx = contexts.get((row.block_number, row.log_index))
            if ctx is None:
                raise ValueError(
                    f"no reference price for the swap at block {row.block_number} "
                    f"log {row.log_index}"
                )
            last_p0 = ctx.p0
            sqrt, tick = _need(row, "sqrt_price_x96"), _need(row, "tick")
            rep = reproduce_swap(state.book, _need(row, "amount0"), _need(row, "amount1"), sqrt)
            if rep is None or rep.run is None:
                if rep is None:
                    unmatched.append({"block": row.block_number, "log_index": row.log_index})
                else:
                    modes[rep.mode] += 1
                state.book.apply_swap(sqrt, tick)
                continue
            modes[rep.mode] += 1
            records.extend(
                state.swap(
                    row.block_number,
                    row.log_index,
                    rep.run,
                    rep.zero_for_one,
                    sqrt,
                    tick,
                    ctx.p0,
                    ctx.p12,
                    ctx.flow_label,
                    ctx.ts_us,
                )
            )
        elif row.event == "mint":
            state.mint(_need(row, "tick_lower"), _need(row, "tick_upper"), _need(row, "amount"))
            if ledger is not None:
                ledger.on_pool_event(row, state)
        elif row.event == "burn":
            if ledger is not None:
                ledger.on_pool_event(row, state)
            state.burn(_need(row, "tick_lower"), _need(row, "tick_upper"), _need(row, "amount"))
        elif row.event in ("collect", "collect_protocol", "other"):
            if ledger is not None:
                ledger.on_pool_event(row, state)
        elif row.event == "flash":
            if last_p0 is None:
                if not contexts:
                    raise ValueError("no reference price for the flash events")
                last_p0 = next(iter(contexts.values())).p0
            records.extend(
                state.flash(
                    row.block_number,
                    row.log_index,
                    row.paid0 or 0,
                    row.paid1 or 0,
                    last_p0,
                    row.ts_us,
                )
            )
        elif row.event == "set_fee_protocol":
            state.fee_protocol = _need(row, "fee_protocol0_new") + (
                _need(row, "fee_protocol1_new") << 4
            )
        else:
            raise ValueError(
                f"unknown event {row.event!r} at block {row.block_number} log {row.log_index}"
            )
    flush(None)
    if ledger is not None:
        ledger.finish(state)
    steps = pl.DataFrame(records, schema=STEP_SCHEMA, orient="row")
    return WindowRun(
        steps=steps,
        modes=dict(modes),
        unmatched=unmatched,
        captures=captures,
        zero_liquidity_steps=int((~steps["accrued"]).sum()) if steps.height else 0,
        null_12s_steps=int(steps["lvr_12_missing"].sum()) if steps.height else 0,
    )
