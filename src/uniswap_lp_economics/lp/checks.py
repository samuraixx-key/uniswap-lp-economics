"""Checks L1-L7 (gated) and the reported checks of sub-project 3 (spec section 9)."""

from typing import Any

import polars as pl

from uniswap_lp_economics.io import hex_u256
from uniswap_lp_economics.lp.positions import LedgerData
from uniswap_lp_economics.validate import MAX_LISTED, CheckResult


def check_l1(swap_fees: pl.DataFrame) -> CheckResult:
    """Every swap re-simulated bit-exactly in one of the reproduction modes."""
    modes = swap_fees.group_by("mode").len().drop_nulls("mode")
    counts: dict[str, Any] = dict(zip(modes["mode"].to_list(), modes["len"].to_list(), strict=True))
    bad = swap_fees.filter(pl.col("mode").is_null())
    listed = [
        {"block": b, "log_index": li}
        for b, li in bad.select("block_number", "log_index").head(MAX_LISTED).iter_rows()
    ]
    return CheckResult(
        "L1 every swap reproduced bit-exactly",
        bad.height == 0 and swap_fees.height > 0,
        {"swaps": swap_fees.height, "unreproduced": bad.height, "by_mode": counts},
        listed,
    )


def check_l2(captures: dict[int, dict[str, Any]], sample_fees: pl.DataFrame) -> CheckResult:
    """Engine fee accumulators vs on-chain fee state at the sample blocks, exactly."""
    bad: list[dict[str, Any]] = []
    n_bad = compared = 0
    blocks = sorted(set(sample_fees["block"].to_list()))
    for b, kind, tick, f0, f1 in sample_fees.select(
        "block", "kind", "tick", "fee_growth0", "fee_growth1"
    ).iter_rows():
        compared += 1
        cap = captures.get(b)
        if cap is None:
            got: tuple[int, int] | None = None
        elif kind == "global":
            got = (cap["global0"], cap["global1"])
        else:
            got = cap["ticks"].get(tick)
        want = (hex_u256(f0), hex_u256(f1))
        if got != want:
            n_bad += 1
            if len(bad) < MAX_LISTED:
                bad.append({"block": b, "kind": kind, "tick": tick, "onchain": want, "engine": got})
    return CheckResult(
        "L2 fee accumulators match the chain",
        n_bad == 0 and compared > 0 and all(b in captures for b in blocks),
        {"blocks": len(blocks), "values_compared": compared, "mismatches": n_bad},
        bad,
    )


def check_l5(
    start: pl.DataFrame, snapshot_ticks: pl.DataFrame, meta: dict[str, int]
) -> CheckResult:
    """Positions open at the snapshot rebuild the snapshot tick book exactly."""
    gross: dict[int, int] = {}
    net: dict[int, int] = {}
    active = 0
    for lo, hi, liq in start.select("tick_lower", "tick_upper", "liquidity").iter_rows():
        for t, sign in ((lo, 1), (hi, -1)):
            gross[t] = gross.get(t, 0) + liq
            net[t] = net.get(t, 0) + sign * liq
        if lo <= meta["tick"] < hi:
            active += liq
    chain = {
        t: (g, nn)
        for t, g, nn in snapshot_ticks.select(
            "tick", "liquidity_gross", "liquidity_net"
        ).iter_rows()
    }
    bad: list[dict[str, Any]] = []
    n_bad = 0
    for t in sorted(set(chain) | set(gross)):
        rebuilt = (gross.get(t, 0), net.get(t, 0))
        if chain.get(t, (0, 0)) != rebuilt:
            n_bad += 1
            if len(bad) < MAX_LISTED:
                bad.append({"tick": t, "onchain": chain.get(t), "rebuilt": rebuilt})
    active_ok = active == meta["liquidity"]
    return CheckResult(
        "L5 positions rebuild the snapshot tick book",
        n_bad == 0 and active_ok and start.height > 0,
        {
            "positions_open_at_snapshot": start.height,
            "ticks_compared": len(set(chain) | set(gross)),
            "tick_mismatches": n_bad,
            "active_liquidity_matches": active_ok,
        },
        bad,
    )


_L7_KEY = [
    "block_number",
    "log_index",
    "event",
    "owner",
    "tick_lower",
    "tick_upper",
    "amount",
    "amount0",
    "amount1",
]


def check_l7(
    window_events: pl.DataFrame, history_window: pl.DataFrame, data: LedgerData
) -> CheckResult:
    """The history's window events equal events.parquet, and each belongs to one position."""
    kinds = ["mint", "burn", "collect"]

    def keyed(df: pl.DataFrame) -> set[tuple[Any, ...]]:
        return set(df.filter(pl.col("event").is_in(kinds)).select(_L7_KEY).iter_rows())

    ours, theirs = keyed(window_events), keyed(history_window)
    missing, extra = ours - theirs, theirs - ours
    unassigned = [k for k in ours if (k[0], k[1]) not in data.pool_event_position]
    listed = [
        {"block": k[0], "log_index": k[1], "issue": "missing_in_history"}
        for k in sorted(missing)[:MAX_LISTED]
    ]
    listed += [
        {"block": k[0], "log_index": k[1], "issue": "no_position"}
        for k in sorted(unassigned)[:MAX_LISTED]
    ]
    return CheckResult(
        "L7 history complete and every event assigned",
        not missing and not extra and not unassigned and len(ours) > 0,
        {
            "window_liquidity_events": len(ours),
            "missing_in_history": len(missing),
            "extra_in_history": len(extra),
            "without_position": len(unassigned),
        },
        listed,
    )
