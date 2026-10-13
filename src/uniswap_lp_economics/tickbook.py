"""Replayable Uniswap V3 liquidity state: per-tick liquidity, current tick, active liquidity."""

from bisect import bisect_right, insort
from dataclasses import dataclass, field

import polars as pl


def _check_range(tick_lower: int, tick_upper: int, amount: int) -> None:
    if tick_lower >= tick_upper:
        raise ValueError(f"tick_lower {tick_lower} must be below tick_upper {tick_upper}")
    if amount < 0:
        raise ValueError(f"amount must be non-negative, got {amount}")


@dataclass
class TickBook:
    tick: int
    sqrt_price_x96: int
    liquidity: int
    liquidity_net: dict[int, int] = field(default_factory=dict)
    liquidity_gross: dict[int, int] = field(default_factory=dict)
    _sorted: list[int] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._sorted = sorted(self.liquidity_gross)

    @classmethod
    def from_snapshot(cls, ticks: pl.DataFrame, meta: dict[str, int]) -> "TickBook":
        t = ticks["tick"].to_list()
        return cls(
            tick=int(meta["tick"]),
            sqrt_price_x96=int(meta["sqrt_price_x96"]),
            liquidity=int(meta["liquidity"]),
            liquidity_net=dict(zip(t, ticks["liquidity_net"].to_list(), strict=True)),
            liquidity_gross=dict(zip(t, ticks["liquidity_gross"].to_list(), strict=True)),
        )

    def _update(self, t: int, gross_delta: int, net_delta: int) -> None:
        gross = self.liquidity_gross.get(t, 0) + gross_delta
        if gross < 0:
            raise ValueError(f"liquidity_gross at tick {t} would go negative")
        if gross == 0:
            self.liquidity_gross.pop(t, None)
            self.liquidity_net.pop(t, None)
            if t in self._sorted:
                self._sorted.remove(t)
            return
        if t not in self.liquidity_gross:
            insort(self._sorted, t)
        self.liquidity_gross[t] = gross
        self.liquidity_net[t] = self.liquidity_net.get(t, 0) + net_delta

    def _in_range(self, tick_lower: int, tick_upper: int) -> bool:
        return tick_lower <= self.tick < tick_upper

    def apply_mint(self, tick_lower: int, tick_upper: int, amount: int) -> None:
        _check_range(tick_lower, tick_upper, amount)
        if amount == 0:
            return
        self._update(tick_lower, amount, amount)
        self._update(tick_upper, amount, -amount)
        if self._in_range(tick_lower, tick_upper):
            self.liquidity += amount

    def apply_burn(self, tick_lower: int, tick_upper: int, amount: int) -> None:
        _check_range(tick_lower, tick_upper, amount)
        if amount == 0:
            return
        for t in (tick_lower, tick_upper):
            if self.liquidity_gross.get(t, 0) < amount:
                raise ValueError(f"liquidity_gross at tick {t} would go negative")
        self._update(tick_lower, -amount, -amount)
        self._update(tick_upper, -amount, amount)
        if self._in_range(tick_lower, tick_upper):
            self.liquidity -= amount

    def apply_swap(self, sqrt_price_x96: int, tick: int) -> None:
        """Move to the post-swap state, crossing every initialized tick in between.

        Upward, crossing t (old < t <= new) adds liquidity_net[t]; downward, crossing t
        (new < t <= old) subtracts it. This matches V3, where a downward cross sets tick = t - 1.
        """
        lo, hi = sorted((self.tick, tick))
        crossed = self._sorted[bisect_right(self._sorted, lo) : bisect_right(self._sorted, hi)]
        sign = 1 if tick > self.tick else -1
        for t in crossed:
            self.liquidity += sign * self.liquidity_net[t]
        self.tick = tick
        self.sqrt_price_x96 = sqrt_price_x96

    def active_liquidity(self) -> int:
        return self.liquidity

    def initialized_ticks(self) -> list[int]:
        return list(self._sorted)
