"""Gated checks of the strategy experiment."""

from typing import Any

import polars as pl

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1
from uniswap_lp_economics.strategy.cfpool import CfRun
from uniswap_lp_economics.strategy.params import (
    CALIBRATION_TOL,
    JULY_START_US,
    REPORT_START_US,
    S1_REL_TOL,
)
from uniswap_lp_economics.strategy.ranges import attribute, held_from_flows, order_key
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


_SWAP_KEYS = ["block_number", "log_index"]


def check_s1(
    steps: pl.DataFrame,
    positions: pl.DataFrame,
    position_flows: pl.DataFrame,
    snapshot_block: int,
) -> CheckResult:
    """Spec 5.2: `attribute` over each window-active position's own range and liquidity
    reproduces the engine's fee_usd and lvr_0, per position and on the window totals, within
    S1_REL_TOL x max(1, |engine|)."""
    held = held_from_flows(position_flows, snapshot_block).with_columns(
        _start=order_key("start_block", "start_log"), _end=order_key("end_block", "end_log")
    )
    by_pos = held.partition_by("position_id", as_dict=True)
    s = (
        steps.filter(pl.col("accrued"))
        .with_columns(_key=order_key("block_number", "log_index"))
        .sort("_key", "step")
    )
    keys = s["_key"]
    fees, lvrs = [], []
    for pid, lo, hi in positions.select("position_id", "tick_lower", "tick_upper").iter_rows():
        h = by_pos.get((pid,))
        if h is None:
            fees.append(0.0)
            lvrs.append(0.0)
            continue
        # only the steps of the position's span go to attribute: most positions are short
        span = h.select(pl.col("_start").min(), pl.col("_end").max()).row(0)
        i0, i1 = (keys.search_sorted(k, "left") for k in span)
        a = attribute(
            s.slice(i0, i1 - i0),
            h.with_columns(tick_lower=pl.lit(lo, pl.Int64), tick_upper=pl.lit(hi, pl.Int64)),
        )
        fees.append(float(a["fee_usd"].sum()))
        lvrs.append(float(a["lvr_0"].sum()))
    cmp = positions.select(
        "position_id",
        fee_got=pl.Series(fees, dtype=pl.Float64),
        fee_engine="fee_usd",
        lvr_got=pl.Series(lvrs, dtype=pl.Float64),
        lvr_engine="lvr_0",
    )
    total = cmp.select(
        position_id=pl.lit("window total"), **{c: pl.col(c).sum() for c in cmp.columns[1:]}
    )

    def rel(m: str) -> pl.Expr:
        engine = pl.col(f"{m}_engine")
        return (pl.col(f"{m}_got") - engine).abs() / pl.max_horizontal(1.0, engine.abs())

    errs = pl.concat([cmp, total]).with_columns(err_fee=rel("fee"), err_lvr=rel("lvr"))
    bad = errs.filter((pl.col("err_fee") > S1_REL_TOL) | (pl.col("err_lvr") > S1_REL_TOL))
    per_pos = errs.head(cmp.height)
    worst = per_pos.sort(pl.max_horizontal("err_fee", "err_lvr"))["position_id"]
    return CheckResult(
        "S1 range attribution vs engine",
        bad.height == 0,
        {
            "positions": cmp.height,
            "max_rel_error_fee": errs["err_fee"].max(),
            "max_rel_error_lvr": errs["err_lvr"].max(),
            "failures": bad.height,
            "worst_position": worst[-1] if worst.len() else None,
        },
        bad.to_dicts()[:MAX_LISTED],
    )


def _key_frame(keys: set[tuple[int, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        list(keys), schema={"block_number": pl.Int64, "log_index": pl.Int64}, orient="row"
    )


def replaced_keys(aligned: pl.DataFrame, tx_other_logs: pl.DataFrame) -> set[tuple[int, int]]:
    """Spec 6.1: the single-pool searcher swaps (searcher, and no other logs in the transaction).

    A swap whose transaction has no other-logs row is kept."""
    r = aligned.join(
        tx_other_logs.select("tx_hash", "other_logs"), on="tx_hash", how="left"
    ).filter((pl.col("flow_label") == "searcher") & (pl.col("other_logs") == 0))
    return set(r.select(*_SWAP_KEYS).iter_rows())


def sandwich_legs(aligned: pl.DataFrame, replaced: set[tuple[int, int]]) -> dict[str, float]:
    """Replaced swaps that look like sandwich legs (spec 6.1 caveat).

    A swap is a leg when some later swap of the same sender in the block goes the opposite way
    and another sender's swap lies between them. gross_usd is the 0 s markout of the legs;
    notional_share is their share of the replaced notional."""
    group = ["block_number", "sender"]
    # _others = other senders' swaps before this one in the block; one lies between two swaps of
    # a sender exactly when their _others differ
    s = (
        aligned.sort(*_SWAP_KEYS)
        .with_columns(
            _others=pl.int_range(pl.len()).over("block_number") - pl.int_range(pl.len()).over(group)
        )
        .select(*group, "log_index", "zero_for_one", "_others")
    )
    pairs = s.join(s, on=group, suffix="_b").filter(
        (pl.col("_others_b") > pl.col("_others"))
        & (pl.col("zero_for_one_b") != pl.col("zero_for_one"))
    )
    legs_keys = pl.concat(
        [
            pairs.select(*_SWAP_KEYS),
            pairs.select("block_number", log_index="log_index_b"),
        ]
    ).unique()
    rep = aligned.join(_key_frame(replaced), on=_SWAP_KEYS, how="semi")
    legs = rep.join(legs_keys, on=_SWAP_KEYS, how="semi")
    non_top = legs.filter(~pl.col("is_top_bot"))
    total = float(rep["notional_usd"].sum())
    return {
        "legs": legs.height,
        "gross_usd": float(legs["markout_usd_0"].sum()),
        "notional_share": float(legs["notional_usd"].sum()) / total if total else 0.0,
        "non_top_legs": non_top.height,
        "non_top_gross_usd": float(non_top["markout_usd_0"].sum()),
    }


def min_profit_gas(aligned: pl.DataFrame, replaced: set[tuple[int, int]], end_us: int) -> int:
    """Spec 6.3: median gas used by the distinct transactions of replaced swaps with t0 in
    [JULY_START_US, end_us)."""
    txs = (
        aligned.join(_key_frame(replaced), on=_SWAP_KEYS, how="semi")
        .filter((pl.col("t0_us") >= JULY_START_US) & (pl.col("t0_us") < end_us))
        .unique("tx_hash")
    )
    if txs.height == 0:
        raise ValueError("no replaced transaction in July to take the gas from")
    return round(float(txs.select(pl.col("receipt_gas_used").median()).item()))


def check_s3(
    model: CfRun,
    swap_steps: pl.DataFrame,
    aligned: pl.DataFrame,
    swap_fees: pl.DataFrame,
    replaced: set[tuple[int, int]],
    sensitivity: CfRun,
    end_us: int = REPORT_START_US,
) -> CheckResult:
    """Spec 6.4: the 5 bp model's arbitrage LVR (0 s) and fees before the protocol's cut against
    the measured values on the replaced swaps; both within CALIBRATION_TOL passes. Reported.

    The +1 s run (`sensitivity`) is reported alongside (`*_1s`) and does not set the verdict.
    Both sides count July only: replaced swaps with t0 in [JULY_START_US, end_us) and the runs'
    days in that span, so full-window inputs give the same verdict as July-cut ones. `end_us` is
    the July end (the split), a day boundary."""
    in_july = (pl.col("t0_us") >= JULY_START_US) & (pl.col("t0_us") < end_us)
    keys = (
        aligned.filter(in_july)
        .select(*_SWAP_KEYS)
        .join(_key_frame(replaced), on=_SWAP_KEYS, how="semi")
    )
    july_days = pl.col("day").is_between(
        pl.from_epoch(pl.lit(JULY_START_US), "us").dt.date(),
        pl.from_epoch(pl.lit(end_us), "us").dt.date(),
        closed="left",
    )
    measured_lvr = float(swap_steps.join(keys, on=_SWAP_KEYS, how="semi")["lvr_0"].sum())
    usd_per_raw = (
        pl.when(pl.col("fee_token") == "USDC")
        .then(1 / 10**DECIMALS0)
        .otherwise(pl.col("p_cex_0") / 10**DECIMALS1)
    )
    measured_fee = float(
        swap_fees.join(keys, on=_SWAP_KEYS, how="semi")
        .join(aligned.select(*_SWAP_KEYS, "p_cex_0"), on=_SWAP_KEYS, how="left")
        .select((pl.col("fee_raw").cast(pl.Float64) * usd_per_raw).sum())
        .item()
    )

    def ratios(run: CfRun) -> tuple[float, float, float | None, float | None]:
        july = run.daily.filter(july_days)
        lvr = float(july["lvr_arb_usd"].sum())
        fee = float(july["fee_arb_total_usd"].sum())
        return (
            lvr,
            fee,
            lvr / measured_lvr if measured_lvr else None,
            fee / measured_fee if measured_fee else None,
        )

    lvr, fee, lvr_ratio, fee_ratio = ratios(model)
    _, _, lvr_1s, fee_1s = ratios(sensitivity)
    bad = [
        {"measure": m, "ratio": x}
        for m, x in (("lvr", lvr_ratio), ("fee", fee_ratio))
        if x is None or abs(x - 1) > CALIBRATION_TOL
    ]
    return CheckResult(
        "S3 calibration (July)",
        not bad,
        {
            "lvr_ratio": lvr_ratio,
            "fee_ratio": fee_ratio,
            "lvr_ratio_1s": lvr_1s,
            "fee_ratio_1s": fee_1s,
            "model_lvr_usd": lvr,
            "model_fee_usd": fee,
            "measured_lvr_usd": measured_lvr,
            "measured_fee_usd": measured_fee,
            "replaced_swaps": keys.height,
            "tolerance": CALIBRATION_TOL,
        },
        bad,
        reported=True,
    )
