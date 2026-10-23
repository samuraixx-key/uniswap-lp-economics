"""Analysis checks A1-A6 (spec 7). A1-A4 gate `ulpe analyze`; A5 and A6 are reported only."""

from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics import flows
from uniswap_lp_economics.config import HORIZONS_S, US
from uniswap_lp_economics.markouts import STALE_S
from uniswap_lp_economics.replay import iter_swaps_with_pre_state, required
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3swap import check_swap_event, swap_check_ok
from uniswap_lp_economics.validate import MAX_LISTED, CheckResult, write_report

A3_TOL_USD = 1e-6
BLOCK_SLOT_US = 12 * US


def check_a1(events: pl.DataFrame, book: TickBook, fee_protocol: int) -> CheckResult:
    """Every historical swap re-simulated from its replayed pre-swap state (plan Ruling 2)."""
    n = exact = bad = skipped = 0
    worst_sqrt, worst_out = 0.0, 0
    listed: list[dict[str, Any]] = []
    for row in iter_swaps_with_pre_state(events, book, fee_protocol):
        c = check_swap_event(
            book,
            required(row, "amount0"),
            required(row, "amount1"),
            required(row, "sqrt_price_x96"),
        )
        if c is None:
            skipped += 1
            continue
        n += 1
        exact += c.exact
        worst_sqrt = max(worst_sqrt, c.sqrt_rel_err)
        worst_out = max(worst_out, c.out_abs_err)
        if not swap_check_ok(c):
            bad += 1
            if len(listed) < MAX_LISTED:
                listed.append(
                    {
                        "block": row.block_number,
                        "log_index": row.log_index,
                        "sqrt_rel_err": c.sqrt_rel_err,
                        "out_abs_err": c.out_abs_err,
                        "out_expected": c.out_expected,
                        "amount_in": c.amount_in,
                    }
                )
    return CheckResult(
        "A1 v3swap reproduces every swap",
        bad == 0 and n > 0,
        {
            "swaps": n,
            "bit_exact": exact,
            "outside_tolerance": bad,
            "no_input_skipped": skipped,
            "max_sqrt_rel_err": worst_sqrt,
            "max_out_abs_err": worst_out,
        },
        listed,
    )


def check_a2(
    series: pl.DataFrame,
    blocks: pl.DataFrame,
    events: pl.DataFrame,
    first_block: int,
    window_end_us: int,
) -> CheckResult:
    """Block series complete and consistent (plan Ruling 3), and the block table reaches the end
    of the window and covers every event (sub-project 3, P3)."""
    last = int(blocks["block_number"].max()) if blocks.height else first_block - 1  # type: ignore[arg-type]
    expected = set(range(first_block, last + 1))
    present = set(series["block_number"].to_list())
    missing = len(expected - present)
    dupes = series.height - series["block_number"].n_unique()
    first_ok = blocks.height > 0 and int(blocks["block_number"].min()) == first_block  # type: ignore[arg-type]
    state = ["sqrt_price_x96", "tick", "liquidity"]
    s = series.sort("block_number").with_columns(
        prev_block=pl.col("block_number").shift(1),
        **{f"prev_end_{c}": pl.col(f"end_{c}").shift(1) for c in state},
    )
    differs_from_prev = pl.any_horizontal([pl.col(c) != pl.col(f"prev_end_{c}") for c in state])
    bad_continuity = s.filter(
        (pl.col("block_number") - pl.col("prev_block") == 1) & differs_from_prev
    ).height
    last_swap = (
        events.filter(pl.col("event") == "swap")
        .sort("block_number", "log_index")
        .group_by("block_number", maintain_order=True)
        .agg(last_sqrt=pl.col("sqrt_price_x96").last())
    )
    bad_end = (
        s.join(last_swap, on="block_number", how="inner")
        .filter(pl.col("end_sqrt_price_x96") != pl.col("last_sqrt"))
        .height
    )
    changed = pl.any_horizontal([pl.col(c) != pl.col(f"end_{c}") for c in state])
    bad_idle = s.filter((pl.col("n_events") == 0) & changed).height
    last_ts_us = (
        int(blocks["block_timestamp"].dt.epoch("us").max())  # type: ignore[arg-type]
        if blocks.height
        else 0
    )
    reaches_end = blocks.height > 0 and last_ts_us >= window_end_us - BLOCK_SLOT_US
    last_event = events["block_number"].max() if events.height else None
    covers_events = last_event is None or (blocks.height > 0 and last >= int(last_event))  # type: ignore[arg-type]
    passed = (
        series.height > 0
        and first_ok
        and missing == 0
        and dupes == 0
        and bad_continuity == 0
        and bad_end == 0
        and bad_idle == 0
        and reaches_end
        and covers_events
    )
    return CheckResult(
        "A2 block series complete and consistent",
        passed,
        {
            "blocks": series.height,
            "expected_blocks": len(expected),
            "missing": missing,
            "duplicates": dupes,
            "block_table_starts_at_first_block": first_ok,
            "start_differs_from_previous_end": bad_continuity,
            "end_differs_from_last_swap": bad_end,
            "idle_blocks_changed": bad_idle,
            "last_block_within_one_slot_of_window_end": reaches_end,
            "blocks_cover_last_event": covers_events,
        },
    )


def check_a3(aligned: pl.DataFrame, horizons: tuple[int, ...] = HORIZONS_S) -> CheckResult:
    """Trader + LP + protocol fee = 0 on every row that has a markout.

    A row with a markout whose residual is null or NaN (a missing LP markout or fee) is counted as
    `unevaluated` and fails the check; it never passes quietly.
    """
    worst, values, unevaluated = 0.0, 0, 0
    for h in horizons:
        markout = pl.col(f"markout_usd_{h}")
        resid = (markout + pl.col(f"lp_markout_usd_{h}") + pl.col("protocol_fee_usd")).abs()
        evaluated = (resid.is_not_null() & ~resid.is_nan()).fill_null(False)
        m, cnt, missing = aligned.select(
            resid.filter(evaluated).max().alias("worst"),
            evaluated.sum().alias("values"),
            (markout.is_not_null() & ~evaluated).sum().alias("unevaluated"),
        ).row(0)
        worst = max(worst, float(m or 0.0))
        values += int(cnt)
        unevaluated += int(missing)
    return CheckResult(
        "A3 trader + LP + protocol fee = 0",
        worst < A3_TOL_USD and values > 0 and unevaluated == 0,
        {
            "values_checked": values,
            "unevaluated": unevaluated,
            "max_abs_residual_usd": worst,
            "tolerance_usd": A3_TOL_USD,
        },
    )


# A reference older than this is a hole in the Binance data, not a quiet market: the longest gap
# between two ETHUSDC trades in the window is 169 s (C5).
MAX_REF_AGE_S = 600


def check_a4(
    aligned: pl.DataFrame,
    ref_first_us: int,
    end_us: int,
    horizons: tuple[int, ...] = HORIZONS_S,
) -> CheckResult:
    """A reference may be missing only outside the Binance data (plan Ruling 6), and the
    time-zero reference may not be older than MAX_REF_AGE_S (a gap in the trade data would
    otherwise leave swaps with a valid but stale price)."""
    summary: dict[str, Any] = {}
    unexpected = 0
    for h in horizons:
        t = pl.col("t0_us") + h * US
        null = pl.col(f"p_cex_{h}").is_null()
        allowed = (t >= end_us) | (t < ref_first_us)
        n_null = aligned.filter(null).height
        bad = aligned.filter(null & ~allowed).height
        summary[f"null_{h}s"] = n_null
        summary[f"unexpected_null_{h}s"] = bad
        unexpected += bad
    summary["stale_ref_over_5s_at_0s"] = aligned.filter(pl.col("cex_age_s_0") > STALE_S).height
    too_old = aligned.filter(pl.col("cex_age_s_0") > MAX_REF_AGE_S).height
    summary[f"refs_older_than_{MAX_REF_AGE_S}s_at_0s"] = too_old
    summary["max_ref_age_s_at_0s"] = aligned["cex_age_s_0"].max()
    return CheckResult(
        "A4 Binance reference coverage",
        unexpected == 0 and too_old == 0 and aligned.height > 0,
        summary,
    )


def check_a5(labelled: pl.DataFrame) -> CheckResult:
    cov = flows.label_coverage(labelled)
    share = dict(zip(cov["flow_label"].to_list(), cov["notional_share"].to_list(), strict=True))
    top = flows.top_unlabelled(labelled, "to_address", 5)
    return CheckResult(
        "A5 label coverage (reported)",
        True,
        {"other_contract_notional_share": share.get("other_contract", 0.0), "by_label": share},
        top.to_dicts(),
        reported=True,
    )


def check_a6(transfers: pl.DataFrame, aligned: pl.DataFrame, blocks: pl.DataFrame) -> CheckResult:
    bot = aligned.filter(pl.col("is_top_bot"))
    bot_txs = bot["tx_hash"].unique()
    in_bot_txs = transfers.filter(pl.col("tx_hash").is_in(bot_txs.implode())).join(
        blocks.select("block_number", "miner"), on="block_number", how="left"
    )
    to_miner = in_bot_txs.filter(pl.col("to_address") == pl.col("miner")).height
    with_payment = bot.filter(pl.col("coinbase_usd") > 0)["tx_hash"].n_unique()
    n_txs = bot_txs.len()
    return CheckResult(
        "A6 builder payments (reported)",
        True,
        {
            "top_bot_txs": n_txs,
            "transfers_to_miner": to_miner,
            "transfers_to_others": in_bot_txs.height - to_miner,
            "txs_with_coinbase_payment": with_payment,
            "share_txs_with_coinbase_payment": with_payment / n_txs if n_txs else None,
            "top_bot_txs_without_scope": bot.filter(pl.col("tx_scope").is_null())[
                "tx_hash"
            ].n_unique(),
        },
        reported=True,
    )


def write_checks(results: list[CheckResult], out_dir: Path, extra: dict[str, Any]) -> str:
    return write_report(results, out_dir, extra, stem="analysis_checks", title="Analysis checks")
