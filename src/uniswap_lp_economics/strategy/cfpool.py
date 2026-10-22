"""The carried-forward counterfactual pool (spec 6.1).

A copy of the snapshot TickBook is advanced through the window's pool events: mints and burns as
observed, every kept swap re-executed in its own mode (L1's) at the block's fee, flash loans
paying that fee on their observed amounts. Nothing resets to the real state between blocks.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol

import polars as pl

from uniswap_lp_economics.align import reference_at, reference_table
from uniswap_lp_economics.config import FEE_PIPS, US
from uniswap_lp_economics.lp.engine import EngineRow, _day, _need, iter_engine_rows
from uniswap_lp_economics.lp.state import step_values
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import (
    MAX_TICK,
    MIN_TICK,
    get_sqrt_ratio_at_tick,
    get_tick_at_sqrt_ratio,
    sqrt_price_x96_to_eth_price,
)
from uniswap_lp_economics.v3swap import (
    SwapRun,
    SwapStep,
    next_initialized_tick_within_one_word,
    swap,
)

_HUGE = 2**128  # an unlimited input: the price limit stops the swap (as in v3swap)

CF_STEP_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,  # -1 for a simulated arbitrage step
    "step": pl.Int64,
    "zero_for_one": pl.Boolean,
    "source": pl.String,  # "arb" | "kept" | "flash"
    "ts_us": pl.Int64,
    "day": pl.Date,
    "p0": pl.Float64,  # the price fee_usd and lvr_0 are valued at
    "liquidity": pl.Int128,
    "sqrt_start": pl.Int128,
    "sqrt_end": pl.Int128,
    "tick_start": pl.Int64,
    "amount_in": pl.Int128,
    "amount_out": pl.Int128,
    "fee": pl.Int128,
    "protocol_fee": pl.Int128,
    "lp_fee": pl.Int128,
    "crossed_tick": pl.Int64,
    "fee_usd": pl.Float64,
    "lvr_0": pl.Float64,
    "accrued": pl.Boolean,
}
BLOCK_END_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "tick": pl.Int64,
    "liquidity": pl.Int128,
}
COUNT_KEYS = (
    "mode_exact_input",
    "mode_exact_output",
    "mode_to_price",
    "no_input",
    "to_price_skipped",
)
_REF_COLUMNS = {0.0: "p_ref_0", 1.0: "p_ref_1"}


class FeeRule(Protocol):
    name: str

    def block_fee_pips(self, pool_price: float, p_ref: float | None) -> int: ...

    def end_block(self, pool_price: float) -> None: ...


@dataclass
class FixedFee:
    pips: int
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.name = f"fixed_{self.pips / 100:g}bp"

    def block_fee_pips(self, pool_price: float, p_ref: float | None) -> int:
        return self.pips

    def end_block(self, pool_price: float) -> None:
        pass


class SwapInfo(NamedTuple):
    p0: float
    mode: str
    replaced: bool


@dataclass
class CfInputs:
    rows: list[EngineRow]
    book: TickBook
    fee_protocol: int
    blocks: pl.DataFrame
    swaps: dict[tuple[int, int], SwapInfo]


@dataclass
class CfRun:
    daily: pl.DataFrame
    counts: dict[str, int]
    steps: pl.DataFrame | None
    block_end: pl.DataFrame | None


def prepare_inputs(
    events: pl.DataFrame,
    ticks: pl.DataFrame,
    meta: dict[str, int],
    aligned: pl.DataFrame,
    swap_fees: pl.DataFrame,
    blocks_state: pl.DataFrame,
    blocks: pl.DataFrame,
    trades: pl.DataFrame,
    replaced: set[tuple[int, int]],
    end_us: int,
) -> CfInputs:
    """Window pool events, the snapshot book, one row per window block, one entry per swap."""
    ref = reference_table(trades)
    bs = (
        blocks_state.select("block_number", "ts_us")
        .join(
            blocks.select("block_number", base_fee_wei=pl.col("base_fee_per_gas").cast(pl.Int64)),
            on="block_number",
            how="left",
        )
        .sort("block_number")
    )
    per_block = bs.with_columns(
        day=pl.from_epoch("ts_us", "us").dt.date(),
        p_ref_0=reference_at(bs["ts_us"], ref, end_us)["price"],
        p_ref_1=reference_at(bs["ts_us"] + US, ref, end_us)["price"],
    ).select("block_number", "ts_us", "day", "base_fee_wei", "p_ref_0", "p_ref_1")
    modes = {
        (b, li): m for b, li, m in swap_fees.select("block_number", "log_index", "mode").iter_rows()
    }
    swaps = {
        (b, li): SwapInfo(float(p0), modes.get((b, li)) or "no_input", (b, li) in replaced)
        for b, li, p0 in aligned.select("block_number", "log_index", "p_cex_0").iter_rows()
    }
    return CfInputs(
        rows=list(iter_engine_rows(events)),
        book=TickBook.from_snapshot(ticks, meta),
        fee_protocol=int(meta["fee_protocol"]),
        blocks=per_block,
        swaps=swaps,
    )


def reexecute(
    book: TickBook, mode: str, amount0: int, amount1: int, sqrt_logged: int, fee_pips: int
) -> SwapRun | None:
    """A logged swap re-run from `book` in its L1 mode; None when it executes nothing.

    Nothing executes for a swap with no input, nor for a to-price swap whose limit the book's
    price has already reached or passed (V3 reverts it with SPL)."""
    if mode == "no_input":
        return None
    zero_for_one = amount0 > 0
    amount_in, amount_out = (amount0, -amount1) if zero_for_one else (amount1, -amount0)
    if mode == "exact_input":
        return swap(book, zero_for_one, amount_in, fee_pips=fee_pips)
    if mode == "exact_output":
        return swap(book, zero_for_one, -amount_out, fee_pips=fee_pips)
    if mode != "to_price":
        raise ValueError(f"unknown swap mode {mode!r}")
    passed = (
        sqrt_logged >= book.sqrt_price_x96 if zero_for_one else sqrt_logged <= book.sqrt_price_x96
    )
    if passed:
        return None
    return swap(book, zero_for_one, _HUGE, sqrt_logged, fee_pips)


def _tick_after(book: TickBook, tick: int, zero_for_one: bool, s: SwapStep) -> int:
    """The pool's tick after one step, set as UniswapV3Pool.swap sets it."""
    tick_next, _ = next_initialized_tick_within_one_word(book, tick, zero_for_one)
    tick_next = max(MIN_TICK, min(MAX_TICK, tick_next))
    if s.sqrt_end == get_sqrt_ratio_at_tick(tick_next):
        return tick_next - 1 if zero_for_one else tick_next
    if s.sqrt_end != s.sqrt_start:
        return get_tick_at_sqrt_ratio(s.sqrt_end)
    return tick


def run_pool(
    ci: CfInputs,
    rule: FeeRule,
    replace: bool,
    ref_offset_s: float = 0.0,
    min_profit_gas: int | None = None,
    keep_steps: bool = False,
) -> CfRun:
    """Replay the window through a copy of `ci.book` at `rule`'s fee (spec 6.1).

    counts: mode_<mode> = kept swaps re-executed in that mode; no_input and to_price_skipped =
    kept swaps that executed nothing (the book is unchanged)."""
    if replace:
        # shortcut: no simulated arbitrage yet, so replacing flow is refused until it exists
        raise NotImplementedError("replacing flow needs the simulated arbitrage")
    p_ref = dict(ci.blocks.select("block_number", _REF_COLUMNS[ref_offset_s]).iter_rows())
    book = copy.deepcopy(ci.book)
    fee_protocol = ci.fee_protocol
    counts = dict.fromkeys(COUNT_KEYS, 0)
    steps: list[tuple[Any, ...]] = []
    ends: list[tuple[int, int, int, int]] = []
    block: int | None = None
    fee = 0
    last_p0: float | None = None

    def close(b: int) -> None:
        rule.end_block(sqrt_price_x96_to_eth_price(book.sqrt_price_x96))
        ends.append((b, book.sqrt_price_x96, book.tick, book.liquidity))

    for row in ci.rows:
        b, li = row.block_number, row.log_index
        if b != block:
            if block is not None:
                close(block)
            block = b
            fee = rule.block_fee_pips(
                sqrt_price_x96_to_eth_price(book.sqrt_price_x96), p_ref.get(b)
            )
        day = _day(row.ts_us)
        if row.event == "swap":
            info = ci.swaps.get((b, li))
            if info is None:
                raise ValueError(f"no reference price for the swap at block {b} log {li}")
            last_p0 = info.p0
            amount0 = _need(row, "amount0")
            run = reexecute(
                book, info.mode, amount0, _need(row, "amount1"), _need(row, "sqrt_price_x96"), fee
            )
            if run is None:
                counts["no_input" if info.mode == "no_input" else "to_price_skipped"] += 1
                continue
            counts[f"mode_{info.mode}"] += 1
            zero_for_one = amount0 > 0
            tick = book.tick
            for i, s in enumerate(run.steps):
                cut, lp_fee, fee_usd, lvr0 = step_values(
                    s.fee, s.amount_in, s.amount_out, zero_for_one, fee_protocol, info.p0
                )
                if keep_steps:
                    steps.append(
                        (b, li, i, zero_for_one, "kept", row.ts_us, day, info.p0, s.liquidity)
                        + (s.sqrt_start, s.sqrt_end, tick, s.amount_in, s.amount_out, s.fee, cut)
                        + (lp_fee, s.crossed_tick, fee_usd, lvr0, s.liquidity > 0)
                    )
                tick = _tick_after(book, tick, zero_for_one, s)
            assert tick == run.tick, (b, li, tick, run.tick)
            book.apply_swap(run.sqrt_price_x96, run.tick)
            assert book.liquidity == run.liquidity, (b, li, book.liquidity, run.liquidity)
        elif row.event == "mint":
            book.apply_mint(
                _need(row, "tick_lower"), _need(row, "tick_upper"), _need(row, "amount")
            )
        elif row.event == "burn":
            book.apply_burn(
                _need(row, "tick_lower"), _need(row, "tick_upper"), _need(row, "amount")
            )
        elif row.event in ("collect", "collect_protocol", "other"):
            pass  # no effect on the book
        elif row.event == "flash":
            if last_p0 is None:  # as the engine values a flash before the window's first swap
                if not ci.swaps:
                    raise ValueError("no reference price for the flash events")
                last_p0 = next(iter(ci.swaps.values())).p0
            liquidity, sqrt = book.liquidity, book.sqrt_price_x96
            for i, (zero_for_one, paid) in enumerate(((True, row.paid0), (False, row.paid1))):
                if not paid or paid <= 0:
                    continue
                f = paid * fee // FEE_PIPS  # the counterfactual fee on the observed amount
                cut, lp_fee, fee_usd, _ = step_values(f, 0, 0, zero_for_one, fee_protocol, last_p0)
                if keep_steps:
                    steps.append(
                        (b, li, i, zero_for_one, "flash", row.ts_us, day, last_p0, liquidity)
                        + (sqrt, sqrt, book.tick, 0, 0, f, cut, lp_fee, None, fee_usd, 0.0)
                        + (liquidity > 0,)
                    )
        elif row.event == "set_fee_protocol":
            fee_protocol = _need(row, "fee_protocol0_new") + (_need(row, "fee_protocol1_new") << 4)
        else:
            raise ValueError(f"unknown event {row.event!r} at block {b} log {li}")
    if block is not None:
        close(block)
    return CfRun(
        daily=pl.DataFrame(),
        counts=counts,
        steps=pl.DataFrame(steps, schema=CF_STEP_SCHEMA, orient="row") if keep_steps else None,
        block_end=pl.DataFrame(ends, schema=BLOCK_END_SCHEMA, orient="row"),
    )
