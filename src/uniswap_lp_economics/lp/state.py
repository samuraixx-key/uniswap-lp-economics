"""Pool fee and LVR accumulators on top of the TickBook (spec section 5).

Fees follow UniswapV3Pool and Tick exactly: feeGrowthGlobal{0,1}X128 grows by
mulDiv(lpFee, 2^128, liquidity) per step, a crossed tick's outside value becomes
global - outside, and fee growth inside a range is global - below - above, all modulo 2^256.
Three float accumulators (USD fees, LVR at 0 s and 12 s) use the same mechanics; they start at
zero at the snapshot (plan Ruling 3) because only differences between checkpoints are used.
"""

from dataclasses import dataclass, field
from typing import NamedTuple

import polars as pl

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1
from uniswap_lp_economics.io import hex_u256
from uniswap_lp_economics.lp.swapfees import protocol_cut
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3swap import SwapRun

Q128 = 2**128
U256 = 2**256
FLOAT_NAMES = ("fee_usd", "lvr_0", "lvr_12")
_ZERO = (0.0, 0.0, 0.0)


def sub256(a: int, b: int) -> int:
    return (a - b) % U256


def step_lvr(zero_for_one: bool, amount_in: int, amount_out: int, price: float) -> float:
    """-(pool's USDC change + pool's WETH change x price), the fee excluded (spec section 5).

    Positive when the trader gained against the reference price."""
    if zero_for_one:  # USDC in, WETH out
        d_usdc, d_eth = amount_in / 10**DECIMALS0, -amount_out / 10**DECIMALS1
    else:
        d_usdc, d_eth = -amount_out / 10**DECIMALS0, amount_in / 10**DECIMALS1
    return float(-(d_usdc + d_eth * price))


@dataclass
class FeeAccumulators:
    global0: int = 0
    global1: int = 0
    outside0: dict[int, int] = field(default_factory=dict)
    outside1: dict[int, int] = field(default_factory=dict)
    fglobal: list[float] = field(default_factory=lambda: list(_ZERO))
    foutside: dict[int, list[float]] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, fee_rows: pl.DataFrame, ticks: list[int]) -> "FeeAccumulators":
        """Start state from on-chain fee rows (data.chain_state) for every initialized tick."""
        g = fee_rows.filter(pl.col("kind") == "global")
        if g.height != 1:
            raise ValueError(f"expected one global fee row, got {g.height}")
        acc = cls(global0=hex_u256(g["fee_growth0"][0]), global1=hex_u256(g["fee_growth1"][0]))
        tick_rows = fee_rows.filter(pl.col("kind") == "tick")
        values = {
            t: (hex_u256(a), hex_u256(b))
            for t, a, b in tick_rows.select("tick", "fee_growth0", "fee_growth1").iter_rows()
        }
        for t in ticks:
            if t not in values:
                raise ValueError(f"no on-chain fee row for initialized tick {t}")
            acc.outside0[t], acc.outside1[t] = values[t]
            acc.foutside[t] = list(_ZERO)
        return acc

    def init_tick(self, t: int, current_tick: int) -> None:
        """Tick.update when a tick flips to initialized."""
        if t <= current_tick:
            self.outside0[t], self.outside1[t] = self.global0, self.global1
            self.foutside[t] = list(self.fglobal)
        else:
            self.outside0[t], self.outside1[t] = 0, 0
            self.foutside[t] = list(_ZERO)

    def clear_tick(self, t: int) -> None:
        self.outside0.pop(t, None)
        self.outside1.pop(t, None)
        self.foutside.pop(t, None)

    def cross(self, t: int) -> None:
        """Tick.cross."""
        self.outside0[t] = sub256(self.global0, self.outside0[t])
        self.outside1[t] = sub256(self.global1, self.outside1[t])
        self.foutside[t] = [g - o for g, o in zip(self.fglobal, self.foutside[t], strict=True)]

    def inside(self, lo: int, hi: int, current_tick: int) -> tuple[int, int, list[float]]:
        """Tick.getFeeGrowthInside, for the exact pair and the float accumulators."""
        if current_tick >= lo:
            b0, b1, bf = self.outside0[lo], self.outside1[lo], self.foutside[lo]
        else:
            b0 = sub256(self.global0, self.outside0[lo])
            b1 = sub256(self.global1, self.outside1[lo])
            bf = [g - o for g, o in zip(self.fglobal, self.foutside[lo], strict=True)]
        if current_tick < hi:
            a0, a1, af = self.outside0[hi], self.outside1[hi], self.foutside[hi]
        else:
            a0 = sub256(self.global0, self.outside0[hi])
            a1 = sub256(self.global1, self.outside1[hi])
            af = [g - o for g, o in zip(self.fglobal, self.foutside[hi], strict=True)]
        floats = [g - b - a for g, b, a in zip(self.fglobal, bf, af, strict=True)]
        return sub256(sub256(self.global0, b0), a0), sub256(sub256(self.global1, b1), a1), floats

    def add(
        self, zero_for_one: bool, lp_fee: int, liquidity: int, values: tuple[float, float, float]
    ) -> bool:
        """One swap step. The contract updates fee growth only with liquidity in range."""
        if liquidity <= 0:
            return False
        growth = lp_fee * Q128 // liquidity
        if zero_for_one:
            self.global0 = (self.global0 + growth) % U256
        else:
            self.global1 = (self.global1 + growth) % U256
        for i, v in enumerate(values):
            self.fglobal[i] += v / liquidity
        return True


class StepRecord(NamedTuple):
    block_number: int
    log_index: int
    step: int
    zero_for_one: bool
    flow_label: str
    ts_us: int
    liquidity: int
    amount_in: int
    amount_out: int
    fee: int
    protocol_fee: int
    lp_fee: int
    crossed_tick: int | None
    fee_usd: float
    lvr_0: float
    lvr_12: float
    lvr_12_missing: bool
    accrued: bool


class PoolState:
    """TickBook + fee accumulators + slot0.feeProtocol, advanced event by event."""

    def __init__(self, book: TickBook, acc: FeeAccumulators, fee_protocol: int) -> None:
        self.book = book
        self.acc = acc
        self.fee_protocol = fee_protocol

    def swap(
        self,
        block_number: int,
        log_index: int,
        run: SwapRun,
        zero_for_one: bool,
        sqrt_after: int,
        tick_after: int,
        p0: float,
        p12: float | None,
        flow_label: str,
        ts_us: int,
    ) -> list[StepRecord]:
        """Apply a reproduced swap step by step, then move the book to the logged state."""
        usd_per_raw_in = 1 / 10**DECIMALS0 if zero_for_one else p0 / 10**DECIMALS1
        records = []
        for i, s in enumerate(run.steps):
            cut = protocol_cut(s.fee, self.fee_protocol, zero_for_one)
            lp_fee = s.fee - cut
            fee_usd = lp_fee * usd_per_raw_in
            lvr0 = step_lvr(zero_for_one, s.amount_in, s.amount_out, p0)
            lvr12 = 0.0 if p12 is None else step_lvr(zero_for_one, s.amount_in, s.amount_out, p12)
            accrued = self.acc.add(zero_for_one, lp_fee, s.liquidity, (fee_usd, lvr0, lvr12))
            if s.crossed_tick is not None:
                self.acc.cross(s.crossed_tick)
            records.append(
                StepRecord(
                    block_number,
                    log_index,
                    i,
                    zero_for_one,
                    flow_label,
                    ts_us,
                    s.liquidity,
                    s.amount_in,
                    s.amount_out,
                    s.fee,
                    cut,
                    lp_fee,
                    s.crossed_tick,
                    fee_usd,
                    lvr0,
                    lvr12,
                    p12 is None,
                    accrued,
                )
            )
        self.book.apply_swap(sqrt_after, tick_after)
        return records

    def mint(self, lo: int, hi: int, amount: int) -> None:
        """Ticks flipping to initialized get their outside values first (Tick.update)."""
        for t in (lo, hi):
            if t not in self.book.liquidity_gross:
                self.acc.init_tick(t, self.book.tick)
        self.book.apply_mint(lo, hi, amount)

    def burn(self, lo: int, hi: int, amount: int) -> None:
        """Ticks flipping to uninitialized are cleared after the burn (Tick.clear)."""
        self.book.apply_burn(lo, hi, amount)
        for t in (lo, hi):
            if t not in self.book.liquidity_gross:
                self.acc.clear_tick(t)

    def inside(self, lo: int, hi: int) -> tuple[int, int, list[float]]:
        return self.acc.inside(lo, hi, self.book.tick)
