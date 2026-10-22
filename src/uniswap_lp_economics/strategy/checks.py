"""Gated checks of the strategy experiment."""

from typing import Any

import polars as pl

from uniswap_lp_economics.strategy.cfpool import CfRun
from uniswap_lp_economics.validate import MAX_LISTED, CheckResult

S2_STEP_COLUMNS = (
    "liquidity",
    "amount_in",
    "amount_out",
    "fee",
    "protocol_fee",
    "lp_fee",
    "crossed_tick",
    "fee_usd",
    "lvr_0",
)
_STEP_KEYS = ["block_number", "log_index", "step"]


def _differences(
    got: pl.DataFrame, expected: pl.DataFrame, keys: list[str], kind: str
) -> list[dict[str, Any]]:
    """Rows whose values differ, or that exist on one side only (full join on `keys`)."""
    cols = [c for c in got.columns if c not in keys]
    both = got.join(expected, on=keys, how="full", coalesce=True, suffix="_expected")
    bad = both.filter(
        pl.any_horizontal(pl.col(c).ne_missing(pl.col(f"{c}_expected")) for c in cols)
    )
    out = []
    for r in bad.iter_rows(named=True):
        where = {k: r.get(k) for k in _STEP_KEYS}
        diff = {c: [r[c], r[f"{c}_expected"]] for c in cols if r[c] != r[f"{c}_expected"]}
        out.append({"kind": kind, **where, "got_expected": diff})
    return out


def check_s2(
    run: CfRun, swap_steps: pl.DataFrame, blocks_state: pl.DataFrame, aligned: pl.DataFrame
) -> CheckResult:
    """Spec 6.2: the identity run reproduces the real pool exactly.

    After every block with events: sqrtPriceX96, tick and liquidity vs blocks_state.end_*; every
    step (flash rows included) vs the engine's swap_steps; every swap's protocol fee vs
    aligned.protocol_fee_raw. Exact values, rows on one side only count as mismatches."""
    if run.steps is None or run.block_end is None:
        raise ValueError("S2 needs a run made with keep_steps=True")
    steps = _differences(
        run.steps.select(*_STEP_KEYS, *S2_STEP_COLUMNS),
        swap_steps.select(*_STEP_KEYS, *S2_STEP_COLUMNS),
        _STEP_KEYS,
        "step",
    )
    blocks = _differences(
        run.block_end,
        blocks_state.join(run.block_end.select("block_number"), on="block_number").select(
            "block_number",
            sqrt_price_x96="end_sqrt_price_x96",
            tick="end_tick",
            liquidity="end_liquidity",
        ),
        ["block_number"],
        "block",
    )
    keys = ["block_number", "log_index"]
    swap_cut = (
        run.steps.filter(pl.col("source") == "kept")
        .group_by(keys)
        .agg(pl.col("protocol_fee").sum())
    )
    swaps = _differences(
        aligned.select(*keys)
        .join(swap_cut, on=keys, how="left")
        .select(*keys, protocol_fee=pl.col("protocol_fee").fill_null(0).cast(pl.Int128)),
        aligned.select(*keys, protocol_fee=pl.col("protocol_fee_raw").cast(pl.Int128)),
        keys,
        "swap",
    )
    bad = sorted(
        steps + blocks + swaps,
        key=lambda m: tuple(-1 if m[k] is None else m[k] for k in _STEP_KEYS),
    )
    return CheckResult(
        "S2 identity replay",
        not bad,
        {
            "blocks_compared": run.block_end.height,
            "steps_compared": max(run.steps.height, swap_steps.height),
            "swaps_compared": aligned.height,
            "mismatches": len(bad),
            "first_mismatch": bad[0] if bad else None,
        },
        bad[:MAX_LISTED],
    )
