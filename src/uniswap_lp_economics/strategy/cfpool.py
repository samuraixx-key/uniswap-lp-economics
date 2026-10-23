"""The carried-forward counterfactual pool (spec 6.1).

A copy of the snapshot TickBook is advanced through the window's pool events: mints and burns as
observed, every kept swap re-executed in its own mode (L1's) at the block's fee, flash loans
paying that fee on their observed amounts. Nothing resets to the real state between blocks.
"""

import copy
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, NamedTuple, Protocol

import polars as pl

from uniswap_lp_economics.align import reference_at, reference_table
from uniswap_lp_economics.config import DECIMALS0, DECIMALS1, FEE_PIPS, US
from uniswap_lp_economics.lp.engine import EngineRow, _day, _need, iter_engine_rows
from uniswap_lp_economics.lp.state import step_values
from uniswap_lp_economics.strategy.params import (
    ARB_CEX_FEE_BP,
    BASELINE_FEE_BP,
    FEE_LEVELS_BP,
    MAX_FEE_BP,
    MIN_FEE_BP,
    MOVE_K,
    VOL_HALF_LIFE_BLOCKS,
    VOL_K,
    bp_to_pips,
)
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import (
    MAX_TICK,
    MIN_TICK,
    eth_price_to_sqrt_price_x96,
    get_sqrt_ratio_at_tick,
    get_tick_at_sqrt_ratio,
    sqrt_price_x96_to_eth_price,
)
from uniswap_lp_economics.v3swap import (
    ArbResult,
    SwapRun,
    SwapStep,
    arb_to_price,
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
    "unreproduced",
    "replaced",
    "arb_trades",
    "below_min_profit",
    "no_reference_blocks",
)
# Per day: *_pl = sums of fee_usd / liquidity and lvr_0 / liquidity over accrued steps (flash in
# "kept"); fee_arb_total_usd is before the protocol's cut; arb_in_usd is what the arbitrage put
# in, fee included, so fee_arb_total_usd / arb_in_usd is the fee it was charged.
DAILY_SCHEMA: dict[str, Any] = {
    "day": pl.Date,
    **dict.fromkeys(
        (
            "fee_arb_pl",
            "lvr_arb_pl",
            "fee_kept_pl",
            "lvr_kept_pl",
            "fee_arb_usd",
            "fee_arb_total_usd",
            "lvr_arb_usd",
            "fee_kept_usd",
            "lvr_kept_usd",
            "arb_in_usd",
        ),
        pl.Float64,
    ),
    **dict.fromkeys(("fee_pips_sum", "n_blocks", "n_arb"), pl.Int64),
}
_N_FLOAT = 10
_ARB_IN = 9
_FEE_PIPS_SUM, _N_BLOCKS, _N_ARB = 10, 11, 12
_REF_INDEX = {0.0: 0, 1.0: 1}


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


def _clamped_pips(bp: float) -> int:
    return bp_to_pips(min(max(bp, MIN_FEE_BP), MAX_FEE_BP))


@dataclass
class VolatilityFee:
    """k x an EWMA of squared block-to-block pool log returns (started at 0), spec 6.5."""

    k: float
    half_life_blocks: int
    name: str = field(init=False)
    _ewma: float = field(default=0.0, init=False, repr=False)
    _last: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.name = f"vol_k{self.k:g}_h{self.half_life_blocks}"

    def block_fee_pips(self, pool_price: float, p_ref: float | None) -> int:
        if self._last is None:
            self._last = pool_price
        return _clamped_pips(self.k * math.sqrt(self._ewma) * 1e4)

    def end_block(self, pool_price: float) -> None:
        r = math.log(pool_price / (self._last or pool_price))
        decay = 0.5 ** (1 / self.half_life_blocks)
        self._ewma = decay * self._ewma + (1 - decay) * r * r
        self._last = pool_price


@dataclass
class MoveFee:
    """5 bp + k x |the pool's log return over the previous block|, spec 6.5."""

    k: float
    name: str = field(init=False)
    _move: float = field(default=0.0, init=False, repr=False)
    _last: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.name = f"move_k{self.k:g}"

    def block_fee_pips(self, pool_price: float, p_ref: float | None) -> int:
        if self._last is None:
            self._last = pool_price
        return _clamped_pips(BASELINE_FEE_BP + self.k * self._move * 1e4)

    def end_block(self, pool_price: float) -> None:
        self._move = abs(math.log(pool_price / (self._last or pool_price)))
        self._last = pool_price


@dataclass
class OracleFee:
    """max(5 bp, |basis to the reference at block start|), clamped to 100 bp. Set to the gap the
    arbitrage would close, it leaves the arbitrage no profit below the clamp, so the arbitrage
    trades only at 100 bp: on the arbitrage side the rule is the fixed 100 bp fee."""

    name: str = field(default="oracle", init=False)

    def block_fee_pips(self, pool_price: float, p_ref: float | None) -> int:
        basis = abs(math.log(pool_price / p_ref)) * 1e4 if p_ref else 0.0
        return _clamped_pips(max(BASELINE_FEE_BP, basis))

    def end_block(self, pool_price: float) -> None:
        pass


def rule_grid() -> list[FeeRule]:
    """The 24 fee rules of spec 6.5: fixed levels, volatility and move grids, the oracle bound."""
    return [
        *(FixedFee(bp_to_pips(bp)) for bp in FEE_LEVELS_BP),
        *(VolatilityFee(k, h) for k in VOL_K for h in VOL_HALF_LIFE_BLOCKS),
        *(MoveFee(k) for k in MOVE_K),
        OracleFee(),
    ]


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
        (b, li): SwapInfo(float(p0), modes.get((b, li)) or "unreproduced", (b, li) in replaced)
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


def _arb_limit(r: ArbResult, p_ref: float, fee_pips: int) -> int:
    """The band edge arb_to_price stopped at. An exact-input re-run of r.amount_in without it
    lands short of the edge: V3 rounds the last step differently with no target price."""
    f, c = fee_pips / 1_000_000, ARB_CEX_FEE_BP / 10_000
    edge = p_ref * (1 - f) * (1 - c) if r.direction == "buy_eth" else p_ref * (1 + c) / (1 - f)
    return eth_price_to_sqrt_price_x96(edge)


def run_pool(
    ci: CfInputs,
    rule: FeeRule,
    replace: bool,
    ref_offset_s: float = 0.0,
    min_profit_gas: int | None = None,
    keep_steps: bool = False,
) -> CfRun:
    """Replay the window through a copy of `ci.book` at `rule`'s fee (spec 6.1).

    Every window block (`ci.blocks` and every block with events) is visited in order: the rule
    sets its fee, then with `replace` the simulated arbitrage trades at block start (spec 6.3) and
    the replaced swaps are skipped; the other swaps are re-executed in their own mode.

    counts: mode_<mode> = kept swaps re-executed in that mode; no_input and to_price_skipped =
    kept swaps that executed nothing (the book is unchanged); unreproduced = swaps L1 could not
    reproduce (skipped); replaced = swaps skipped because the arbitrage stands for them;
    arb_trades, below_min_profit (a gap whose profit does not pay the gas) and
    no_reference_blocks (no reference price, no trade)."""
    if replace and min_profit_gas is None:
        raise ValueError("replacing flow needs min_profit_gas")
    ref_i = _REF_INDEX[ref_offset_s]
    rule = copy.deepcopy(rule)  # a rule keeps state; each run starts from a fresh one
    book = copy.deepcopy(ci.book)
    fee_protocol = ci.fee_protocol
    counts = dict.fromkeys(COUNT_KEYS, 0)
    steps: list[tuple[Any, ...]] = []
    ends: list[tuple[int, int, int, int]] = []
    daily: dict[date, list[Any]] = {}
    last_p0: float | None = None
    block_info = {
        r[0]: r[1:]
        for r in ci.blocks.select(
            "block_number", "ts_us", "day", "base_fee_wei", "p_ref_0", "p_ref_1"
        ).iter_rows()
    }
    by_block: dict[int, list[EngineRow]] = {}
    for row in ci.rows:
        by_block.setdefault(row.block_number, []).append(row)

    def apply(
        b: int,
        li: int,
        zero_for_one: bool,
        source: str,
        ts_us: int,
        day: date,
        p0: float,
        run: SwapRun,
        acc: list[Any],
    ) -> None:
        """Value a swap's steps (fees and LVR at p0), add them to the day, move the book."""
        arb = source == "arb"
        usd_per_raw_in = 1 / 10**DECIMALS0 if zero_for_one else p0 / 10**DECIMALS1
        tick = book.tick
        for i, s in enumerate(run.steps):
            cut, lp_fee, fee_usd, lvr0 = step_values(
                s.fee, s.amount_in, s.amount_out, zero_for_one, fee_protocol, p0
            )
            if s.liquidity > 0:
                acc[0 if arb else 2] += fee_usd / s.liquidity
                acc[1 if arb else 3] += lvr0 / s.liquidity
            if arb:
                acc[4] += fee_usd
                acc[5] += s.fee * usd_per_raw_in
                acc[6] += lvr0
                acc[_ARB_IN] += (s.amount_in + s.fee) * usd_per_raw_in
            else:
                acc[7] += fee_usd
                acc[8] += lvr0
            if keep_steps:
                steps.append(
                    (b, li, i, zero_for_one, source, ts_us, day, p0, s.liquidity, s.sqrt_start)
                    + (s.sqrt_end, tick, s.amount_in, s.amount_out, s.fee, cut, lp_fee)
                    + (s.crossed_tick, fee_usd, lvr0, s.liquidity > 0)
                )
            tick = _tick_after(book, tick, zero_for_one, s)
        assert tick == run.tick, (b, li, tick, run.tick)
        book.apply_swap(run.sqrt_price_x96, run.tick)
        assert book.liquidity == run.liquidity, (b, li, book.liquidity, run.liquidity)

    for b in sorted(block_info.keys() | by_block.keys()):
        rows = by_block.get(b, [])
        info = block_info.get(b)
        ts_b, day, base_fee_wei, *refs = info or (
            rows[0].ts_us,
            _day(rows[0].ts_us),
            None,
            None,
            None,
        )
        p_ref = refs[ref_i]
        fee = rule.block_fee_pips(sqrt_price_x96_to_eth_price(book.sqrt_price_x96), p_ref)
        acc = daily.setdefault(day, [0.0] * _N_FLOAT + [0, 0, 0])
        acc[_FEE_PIPS_SUM] += fee
        acc[_N_BLOCKS] += 1
        if replace and p_ref is None:
            counts["no_reference_blocks"] += 1
        elif replace:
            r = arb_to_price(book, p_ref, fee, ARB_CEX_FEE_BP)
            if r.direction != "none":
                if base_fee_wei is None:
                    raise ValueError(f"no base fee for block {b}")
                assert min_profit_gas is not None
                if r.profit_usd > base_fee_wei * min_profit_gas / 1e18 * p_ref:
                    zero_for_one = r.direction == "buy_eth"
                    # the same call arb_to_price made, so the steps land where it said
                    arb_run = swap(book, zero_for_one, _HUGE, _arb_limit(r, p_ref, fee), fee)
                    assert arb_run.amount_out == r.amount_out, (b, arb_run.amount_out, r.amount_out)
                    p0 = refs[0] if refs[0] is not None else p_ref  # LVR at the 0 s reference
                    apply(b, -1, zero_for_one, "arb", ts_b, day, p0, arb_run, acc)
                    counts["arb_trades"] += 1
                    acc[_N_ARB] += 1
                else:
                    counts["below_min_profit"] += 1
        for row in rows:
            li = row.log_index
            if row.event == "swap":
                sw = ci.swaps.get((b, li))
                if sw is None:
                    raise ValueError(f"no reference price for the swap at block {b} log {li}")
                last_p0 = sw.p0
                if replace and sw.replaced:
                    counts["replaced"] += 1
                    continue
                if sw.mode == "unreproduced":
                    counts["unreproduced"] += 1
                    continue
                amount0 = _need(row, "amount0")
                run = reexecute(
                    book, sw.mode, amount0, _need(row, "amount1"), _need(row, "sqrt_price_x96"), fee
                )
                if run is None:
                    counts["no_input" if sw.mode == "no_input" else "to_price_skipped"] += 1
                    continue
                counts[f"mode_{sw.mode}"] += 1
                apply(b, li, amount0 > 0, "kept", row.ts_us, day, sw.p0, run, acc)
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
                    cut, lp_fee, fee_usd, _ = step_values(
                        f, 0, 0, zero_for_one, fee_protocol, last_p0
                    )
                    if liquidity > 0:
                        acc[2] += fee_usd / liquidity
                    acc[7] += fee_usd
                    if keep_steps:
                        steps.append(
                            (b, li, i, zero_for_one, "flash", row.ts_us, day, last_p0, liquidity)
                            + (sqrt, sqrt, book.tick, 0, 0, f, cut, lp_fee, None, fee_usd, 0.0)
                            + (liquidity > 0,)
                        )
            elif row.event == "set_fee_protocol":
                fee_protocol = _need(row, "fee_protocol0_new") + (
                    _need(row, "fee_protocol1_new") << 4
                )
            else:
                raise ValueError(f"unknown event {row.event!r} at block {b} log {li}")
        rule.end_block(sqrt_price_x96_to_eth_price(book.sqrt_price_x96))
        ends.append((b, book.sqrt_price_x96, book.tick, book.liquidity))
    days = (
        pl.date_range(min(daily), max(daily), eager=True).to_list() if daily else []
    )  # every day of the window, zeros where nothing happened
    zero = [0.0] * _N_FLOAT + [0, 0, 0]
    return CfRun(
        daily=pl.DataFrame(
            [(d, *daily.get(d, zero)) for d in days], schema=DAILY_SCHEMA, orient="row"
        ),
        counts=counts,
        steps=pl.DataFrame(steps, schema=CF_STEP_SCHEMA, orient="row") if keep_steps else None,
        block_end=pl.DataFrame(ends, schema=BLOCK_END_SCHEMA, orient="row"),
    )
