"""Checks L1-L7 (gated) and the reported checks of sub-project 3 (spec section 9)."""

from typing import Any

import polars as pl

from uniswap_lp_economics.io import hex_u256
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
