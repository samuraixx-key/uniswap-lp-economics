"""Checks L1-L7 (gated) and the reported checks of sub-project 3 (spec section 9)."""

from typing import Any

import polars as pl

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
