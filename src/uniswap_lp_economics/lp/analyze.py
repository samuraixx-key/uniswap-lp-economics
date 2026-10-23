"""`ulpe lp`: validated data -> LP results (checks L1-L7, tables, summary.json["lp"])."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from uniswap_lp_economics import align, config, flows, report, validate
from uniswap_lp_economics.build import load_snapshot_meta
from uniswap_lp_economics.data import (
    binance,
    block_timing,
    builders,
    chain_state,
    history,
    relays,
    transfers,
)
from uniswap_lp_economics.data import blocks as bq_blocks
from uniswap_lp_economics.io import ordered_group_by, read_exact, write_exact, write_text_atomic
from uniswap_lp_economics.lp import (
    destination,
    figdata,
    lifetime,
    payouts,
    pnl,
    robustness,
    theory,
)
from uniswap_lp_economics.lp.checks import (
    HOLDOUT2_DECISION_FILE,
    check_l1,
    check_l2,
    check_l3,
    check_l4,
    check_l5,
    check_l6,
    check_l7,
    check_r1_relays,
    check_r2_traces_vs_alchemy,
    check_r3_lp_types,
    check_r4_transferred,
    check_r5_null_12s,
    check_r6_robustness,
    holdout2_ready,
    holdout_decision,
    settle_decision,
)
from uniswap_lp_economics.lp.engine import contexts_from_aligned, replay_window
from uniswap_lp_economics.lp.ledger import Ledger
from uniswap_lp_economics.lp.positions import build_positions, liquidity_at
from uniswap_lp_economics.lp.state import FeeAccumulators, PoolState
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import Q96

GROUPINGS = (
    ("lp_type", pnl.LP_TYPES),
    ("width_bucket", pnl.WIDTH_BUCKETS),
    ("holding", pnl.HOLD_BUCKETS),
    ("cohort", pnl.COHORTS),
)
DESTINATION_NOTE = (
    "Every figure here counts every searcher step, including steps with no liquidity in range; "
    "the accrued-only `*_searcher_usd` totals in lp_pnl.md and summary.json do not. Shares are "
    "of LVR on searcher steps."
)
RULE_SPLIT_LABEL = (
    "measured payments; not adopted because its pre-registered recipient check failed"
)
SENSITIVITY_NOTE = (
    "The primary split treats a block whose last transaction is not from its fee recipient as "
    "self-built (proposer share 1). The relay sample shows that most such blocks are MEV-Boost "
    "blocks that paid the proposer some other way, so the sensitivity gives those blocks the "
    "volume-weighted proposer share of the paid blocks instead. Only proposer and builder margin "
    "move; their sum, and every other figure, is the same under both."
)


def classes_note(table: pl.DataFrame) -> str:
    """The payout rule and what it leaves unexplained, read from the class table."""
    un = table.filter(pl.col("cls") == payouts.UNEXPLAINED).row(0, named=True)
    return (
        "A payout address is a sender other than the fee recipient that sent the last "
        f"transaction in at least {payouts.PAYOUT_MIN_BLOCKS} of the fee recipient's blocks, with "
        f"value > 0 in at least {payouts.PAYOUT_MIN_POSITIVE_SHARE:.0%} of them. Blocks left "
        f"unexplained: {un['share_blocks']:.2%} of blocks and {un['share_builder_paid_usd']:.2%} "
        f"of single-pool builder dollars (${un['builder_paid_usd']:,.2f}); they give the "
        "proposer the whole builder revenue."
    )


JIT_NOTE = (
    "JIT per swap: P&L of the jit positions divided by the swaps each was active for (swaps in "
    "its block between its first liquidity add and its last removal, in log order), summed over "
    "position-swap pairs; the median is over jit positions with at least one swap. Costs include "
    "direct payments to the fee recipient in the LP's transactions. Some JIT transactions also "
    "swap in the pool (jit_own_swaps in summary.json): a payment there may be for the swap, and "
    "the rebalancing benchmark takes those swaps as free."
)
PNL_NOTE = (
    "P&L against rebalancing = fees - LVR (0 s) - LP gas - direct payments to the fee recipient "
    "in the LP's transactions; against holding = everything the LP got out minus everything put "
    "in, at the exit price, less the same costs. bp_per_day = P&L / (hourly time-weighted "
    "position value x days). Intervals: 95% bootstrap over positions (1,000 resamples, seed 42)."
)

ROBUSTNESS_NOTE = (
    "LP fees, LVR and fees - LVR with the reference price read at block time + offset_s, for "
    "each reference. Each cell is the headline plus the per-swap shift of the L6 identity "
    "(fees - LVR = amount_usdc + amount_eth x P - protocol fee), so the primary 0 s cell is the "
    "headline. ci: 95% day bootstrap; shift: change from the primary 0 s cell, with a paired "
    "interval (the same 1,000 resampled days, seed 42). n_unpriced: swaps with no price in the "
    "cell (zero shift)."
)
TIMING_NOTE = (
    "Winning-bid time = the earliest bid the delivering relay received with the delivered block "
    "hash, minus slot start, in ms. Only Titan, Flashbots and Aestus publish July 2026 bids "
    "(ultrasound, the largest relay, keeps none for this window). A block can be delivered by "
    "several relays, so a sampled block is timed whenever one of the three delivered it, "
    "including many that ultrasound also delivered. Missing are the blocks none of the three "
    "delivered, or that one delivered but no longer lists (n_delivered_not_timed); they could "
    "be sealed at other times."
)


@dataclass
class LpInputs:
    events: pl.DataFrame
    ticks: pl.DataFrame
    meta: dict[str, int]
    aligned: pl.DataFrame
    blocks_state: pl.DataFrame
    swap_fees: pl.DataFrame
    trades: pl.DataFrame
    pool_history: pl.DataFrame
    npm_history: pl.DataFrame
    snapshot_fees: pl.DataFrame
    sample_fees: pl.DataFrame
    start_positions: pl.DataFrame
    end_positions: pl.DataFrame
    owner_code: pl.DataFrame
    minute_klines: pl.DataFrame
    ethusdt_1s: pl.DataFrame
    lp_labels: pl.DataFrame
    blocks: pl.DataFrame
    block_revenue: pl.DataFrame
    last_tx: pl.DataFrame
    payout_code: pl.DataFrame
    tx_direct: pl.DataFrame
    tx_other_logs: pl.DataFrame
    relays: pl.DataFrame
    bot_transfers: pl.DataFrame
    block_timing: pl.DataFrame
    # Seed-45 holdout payment paths (`ulpe fetch-paths`); empty until fetched.
    payment_paths: pl.DataFrame = field(
        default_factory=lambda: pl.DataFrame(schema=transfers.PATH_SCHEMA)
    )


def _need(path: Path, command: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `ulpe {command}` first")
    return path


def load_lp_inputs(raw: Path, interim: Path, processed: Path, lp_labels_csv: Path) -> LpInputs:
    """Everything `lp_analysis` reads. `events` (interim/events.parquet) carries the transaction
    receipt columns of every pool log, which also covers the position-manager transactions (each
    holds a pool event); the history frames carry no receipts."""
    cs = raw / chain_state.CHAIN_DIR
    pool_history, npm_history = history.load_history(raw)
    block_revenue, tx_direct, tx_other_logs = builders.load_builders(raw)
    swaps = read_exact(_need(interim / "swaps.parquet", "build"))
    top_bots = flows.top_bots(flows.label_swaps(swaps, flows.load_labels(config.LABELS_CSV)))
    return LpInputs(
        events=read_exact(_need(interim / "events.parquet", "build")),
        ticks=read_exact(_need(raw / "tickbook_snapshot.parquet", "fetch-snapshot")),
        meta=load_snapshot_meta(raw),
        aligned=read_exact(_need(processed / "aligned.parquet", "analyze")),
        blocks_state=read_exact(_need(processed / "blocks_state.parquet", "analyze")),
        swap_fees=read_exact(_need(processed / "swap_fees.parquet", "analyze")),
        trades=pl.read_parquet(_need(interim / "cex_ethusdc.parquet", "build")),
        pool_history=pool_history,
        npm_history=npm_history,
        snapshot_fees=read_exact(_need(cs / chain_state.SNAPSHOT_FEES, "fetch-chain-state")),
        sample_fees=read_exact(_need(cs / chain_state.SAMPLE_FEES, "fetch-chain-state")),
        start_positions=read_exact(_need(cs / chain_state.START_POSITIONS, "fetch-chain-state")),
        end_positions=read_exact(_need(cs / chain_state.END_POSITIONS, "fetch-chain-state")),
        owner_code=pl.read_parquet(_need(cs / chain_state.OWNER_CODE, "fetch-chain-state")),
        minute_klines=binance.load_minute_klines(raw),
        ethusdt_1s=pl.read_parquet(_need(interim / "cex_ethusdt_1s.parquet", "build")),
        lp_labels=pnl.load_lp_labels(lp_labels_csv),
        blocks=pl.read_parquet(_need(raw / bq_blocks.BLOCKS_FILE, "fetch-blocks")),
        block_revenue=block_revenue,
        last_tx=builders.load_last_tx(raw),
        payout_code=pl.read_parquet(
            _need(raw / builders.BUILDERS_DIR / builders.PAYOUT_CODE, "fetch-payout-code")
        ),
        tx_direct=tx_direct,
        tx_other_logs=tx_other_logs,
        relays=read_exact(_need(raw / relays.RELAY_FILE, "fetch-relays")),  # wei: Int128
        bot_transfers=transfers.load_bot_transfers(raw, top_bots),
        block_timing=pl.read_parquet(_need(raw / block_timing.TIMING_FILE, "fetch-timing")),
        payment_paths=(
            read_exact(raw / transfers.PATHS_FILE)
            if (raw / transfers.PATHS_FILE).exists()
            else pl.DataFrame(schema=transfers.PATH_SCHEMA)
        ),
    )


def hourly_grid(blocks_state: pl.DataFrame, start_us: int, end_us: int) -> pl.DataFrame:
    """UTC hour starts in [start, end) with the pool price and Binance price in force (plan
    Ruling 5): ts_us, sqrt (sqrtPrice / 2^96 as a float) and p_cex."""
    first = -(-start_us // config.HOUR_US) * config.HOUR_US
    hours = pl.DataFrame(
        {"ts_us": list(range(first, end_us, config.HOUR_US))}, schema={"ts_us": pl.Int64}
    )
    return hours.join_asof(
        blocks_state.select("ts_us", "sqrt_price_x96", "p_cex"), on="ts_us", strategy="backward"
    ).select("ts_us", sqrt=pl.col("sqrt_price_x96").cast(pl.Float64) / Q96, p_cex="p_cex")


def reference_robustness(
    inp: LpInputs,
    daily: pl.DataFrame,
    last_trade: pl.DataFrame,
    totals: dict[str, Any],
    end_us: int,
) -> tuple[pl.DataFrame, dict[str, Any], float, float]:
    """The robustness table, the numbers summary.json quotes from it, and the identity total at
    the primary reference and 0 s (for R6). Sub-project 4 spec sections 5 and 7."""
    swaps = inp.aligned.join(
        inp.swap_fees.select("block_number", "log_index", "lp_fee_raw"),
        on=["block_number", "log_index"],
        how="left",
        validate="1:1",
    )
    refs = {
        "binance_last_trade": last_trade,
        "binance_trade_side_mid": align.trade_side_mid_table(inp.trades),
        "binance_ethusdt_1s_close": align.kline_reference_table(inp.ethusdt_1s),
    }
    shifts = robustness.daily_shifts(swaps, refs, end_us)
    table = robustness.robustness_table(daily, shifts)
    reprice = float(
        shifts.filter(
            (pl.col("reference") == robustness.REFERENCES[0]) & (pl.col("offset_s") == 0)
        )["d_fees_minus_lvr_usd"].sum()
    )

    def line(name: str) -> tuple[list[float], list[float]]:
        rows = table.filter(pl.col("reference") == name).sort("offset_s")
        return rows["offset_s"].to_list(), rows["fees_minus_lvr_usd"].to_list()

    timing = block_timing.timing_summary(inp.block_timing)
    xs, ys = line(robustness.REFERENCES[0])
    p50 = timing["p50_ms"]
    at_zero = table.filter(pl.col("offset_s") == 0).sort(pl.col("shift_usd").abs(), descending=True)
    gap = totals["fees_minus_lvr_usd"]
    summary = {
        "crossing_offset_s": {
            n: robustness.crossing_offset(*line(n), step=n in robustness.STEP_REFERENCES)
            for n in robustness.REFERENCES
        },
        "timing": timing,
        "fees_minus_lvr_at_median_timing_usd": None
        if p50 is None
        else float(np.interp(p50 / 1000, xs, ys)),
        "largest_reference_shift_0s_usd": float(at_zero["shift_usd"][0]),
        "protocol_fees_share_of_gap": totals["protocol_fees_usd"] / -gap if gap < 0 else None,
        "proxy_quality": align.proxy_quality(inp.aligned["t0_us"], inp.trades, end_us),
    }
    identity = float(
        inp.aligned.select(
            (
                pl.col("amount_usdc")
                + pl.col("amount_eth") * pl.col("p_cex_0")
                - pl.col("protocol_fee_usd")
            ).sum()
        ).item()
    )
    return table, summary, identity, reprice


def _decision_line(decision: dict[str, Any], one: bool, frozen: bool) -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.1%}"

    return (
        f"proposer split {'one' if one else 'hedge'}, {decision['n_found_payout']} found payout "
        f"blocks, within 1 wei {pct(decision.get('share_within_1_wei'))}, recipient "
        f"{pct(decision.get('share_recipient_match'))}, {'frozen' if frozen else 'not frozen'}"
    )


def lp_analysis(
    inp: LpInputs,
    results_dir: Path,
    processed_dir: Path,
    provenance: dict[str, Any],
    end_us: int | None = None,
    raw_dir: Path | None = None,
) -> str:
    """`raw_dir` holds the holdout files the decision is frozen against; None never freezes."""
    end_us = align.window_end_us() if end_us is None else end_us
    snap = int(inp.meta["block"])
    data = build_positions(inp.pool_history, inp.npm_history)
    state = PoolState(
        TickBook.from_snapshot(inp.ticks, inp.meta),
        FeeAccumulators.from_rows(inp.snapshot_fees, inp.ticks["tick"].to_list()),
        int(inp.meta["fee_protocol"]),
    )
    ledger = Ledger(data, inp.start_positions, snap)
    capture = {
        int(b): g.filter(pl.col("kind") == "tick")["tick"].to_list()
        for (b,), g in inp.sample_fees.partition_by("block", as_dict=True).items()
    }
    window_npm = inp.npm_history.filter(pl.col("block_number") > snap)
    run = replay_window(
        inp.events, state, contexts_from_aligned(inp.aligned), capture, ledger, window_npm
    )
    accounts = ledger.accounts_frame()
    flows_window = data.flows.filter(pl.col("block_number") > snap)
    results = [
        check_l1(inp.swap_fees, len(run.unmatched)),
        check_l2(run.captures, inp.sample_fees),
        check_l3(ledger, inp.end_positions),
        check_l4(ledger, inp.end_positions, snap),
        check_l5(liquidity_at(data, snap), inp.ticks, inp.meta),
        check_l6(run.steps, accounts, inp.aligned, inp.swap_fees, flows_window.height),
        check_l7(inp.events, inp.pool_history.filter(pl.col("block_number") > snap), data),
    ]
    status = "PASS" if all(r.passed for r in results) else "FAIL"
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.name}: {r.summary}")
    if status != "PASS":
        validate.write_report(
            results, results_dir, provenance, stem="lp_checks", title="LP analysis checks"
        )
        return status
    # From here on nothing is written until every number is computed, so a late error cannot
    # leave this run's checks file beside the previous run's results.

    bs = inp.blocks_state.sort("block_number")
    prices = {b: (t, p) for b, t, p in bs.select("block_number", "ts_us", "p_cex").iter_rows()}
    first, last = bs.row(0, named=True), bs.row(-1, named=True)
    start = pnl.Edge(
        first["block_number"], first["ts_us"], int(inp.meta["sqrt_price_x96"]), first["p_cex"]
    )
    end = pnl.Edge(
        last["block_number"], last["ts_us"], int(last["end_sqrt_price_x96"]), last["p_cex"]
    )
    shares = pnl.cost_shares(flows_window, inp.events, inp.tx_direct, prices)
    gas, direct = pnl.by_position(shares, "gas"), pnl.by_position(shares, "direct")
    grid = hourly_grid(bs, start.ts_us, end.ts_us)
    spans = pnl.position_spans(data.positions, accounts, flows_window, start, end)
    twv = (
        dict(
            pnl.time_weighted_value(
                pnl.liquidity_path(accounts, flows_window, start), spans, grid
            ).iter_rows()
        )
        if grid.height
        else {}  # a window shorter than an hour: every position takes the Ruling-5 fallback
    )
    has_code = dict(inp.owner_code.select("address", "has_code").iter_rows())
    positions = pnl.window_pnl(
        data.positions,
        accounts,
        flows_window,
        prices,
        gas,
        twv,
        set(inp.lp_labels["address"].to_list()),
        has_code,
        start,
        end,
        direct=direct,
    )
    groups = pl.concat(
        [
            pnl.group_table(positions, by, order)
            .rename({by: "group"})
            .with_columns(grouping=pl.lit(by))
            for by, order in GROUPINGS
        ],
        how="diagonal",
    ).select("grouping", "group", pl.exclude("grouping", "group"))

    ref = align.reference_table(inp.trades)
    grid_1s = theory.price_grid(ref, start.ts_us, end.ts_us, 1, end_us)
    grid_1m = theory.price_grid(ref, start.ts_us, end.ts_us, 60, end_us)
    int_1s = theory.interval_theory(grid_1s, bs)
    int_1m = theory.interval_theory(grid_1m, bs)
    daily = theory.measured_daily(run.steps, inp.aligned).join(
        theory.daily_theory(int_1s, int_1m), on="day", how="left"
    )
    no_theory = daily.filter(pl.col("sigma_annual").is_null())
    if no_theory.height:  # theory.regimes would put such days into "high" volatility
        raise ValueError(
            f"{no_theory.height} measured days have no theoretical LVR (no Binance price "
            f"intervals): {no_theory['day'].head(5).to_list()}"
        )
    daily, regime_summary = theory.regimes(daily)
    daily_stats = theory.daily_summary(daily)
    days = ledger.days_frame()
    regime_groups = theory.regime_by_group(days, positions.select("position_id", "lp_type"), daily)

    life = lifetime.lifetime_table(
        data.positions,
        data.flows,
        accounts,
        positions["position_id"].to_list(),
        prices,
        align.kline_reference_table(inp.minute_klines, bar_s=60),
        start.ts_us,
        end,
        window_costs={
            pid: g + d
            for pid, g, d in positions.select("position_id", "gas_usd", "direct_usd").iter_rows()
        },
    )
    life_overall, life_width, life_bucket = lifetime.lifetime_summary(life)

    steps = run.steps
    accrued = steps.filter(pl.col("accrued"))  # steps with no liquidity in range earn no one
    searcher = accrued.filter(pl.col("flow_label") == "searcher")
    shortfalls = data.collect_shortfalls
    jit = pnl.jit_per_swap(positions, flows_window, inp.aligned)
    totals: dict[str, Any] = {
        "lp_fees_usd": float(accrued["fee_usd"].sum()),
        "protocol_fees_usd": float(inp.aligned["protocol_fee_usd"].sum()),
        "lvr_0_usd": float(accrued["lvr_0"].sum()),
        "lvr_12_usd": float(accrued["lvr_12"].sum()),
        "lvr_0_searcher_usd": float(searcher["lvr_0"].sum()),
        "lp_fees_searcher_usd": float(searcher["fee_usd"].sum()),
        "theory_1s_usd": float(daily["theory_1s"].sum()),
        "theory_1m_usd": float(daily["theory_1m"].sum()),
        "theory_arb_usd": float(daily["theory_arb"].sum()),
        "theory_arb_fees_usd": float(daily["theory_arb_fees"].sum()),
        "positions_window_active": positions.height,
        "lp_gas_usd": float(positions["gas_usd"].sum()),
        "lp_direct_payments_usd": float(positions["direct_usd"].sum()),
        "pnl_rebal_total_usd": float(positions["pnl_rebal_usd"].sum()),
        "pnl_hold_total_usd": float(positions["pnl_hold_usd"].sum()),
        "share_positions_beat_hold_window": float((positions["pnl_hold_usd"] > 0).mean())  # type: ignore[arg-type]
        if positions.height
        else None,
        "zero_liquidity_steps": run.zero_liquidity_steps,
        "steps_without_12s_reference": run.null_12s_steps,
        # NPM collects that asked for more than the pool paid (raw units), and zero collects on
        # keys that never held a position: both are reported, neither changes a position.
        "collect_shortfalls": {
            "count": len(shortfalls),
            "max_d0": max((s[3] for s in shortfalls), default=0),
            "max_d1": max((s[4] for s in shortfalls), default=0),
        },
        "noop_collects": len(data.noop_collects),
        "n_excluded_carry": life_overall["n_excluded_carry"],
    }
    totals["fees_minus_lvr_usd"] = totals["lp_fees_usd"] - totals["lvr_0_usd"]

    # Plan Ruling 10: keep what `ulpe analyze` wrote, replace only the "lp" key. Read it now, so
    # a missing or unreadable summary stops the run before anything is written.
    summary_path = _need(results_dir / "summary.json", "analyze")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["lp"] = {
        **provenance,
        **totals,
        "regimes": regime_summary.to_dicts(),
        "groups": groups.to_dicts(),
        "jit_per_swap": jit,
        "jit_own_swaps": pnl.jit_own_swaps(positions, flows_window, inp.aligned, shares),
        "daily": daily_stats,
        "lifetime": life_overall,
        "lifetime_by_width": life_width.to_dicts(),
        "lifetime_by_life": life_bucket.to_dicts(),
        "checks": {r.name: r.summary for r in results},
    }
    # Where LVR goes (spec section 7), and the reported checks R1-R5: neither gates the run.
    classes = payouts.block_classes(inp.block_revenue, inp.last_tx)
    # R1 and the decision test the payout rule, so they use the payouts=True split; the published
    # split is that one only when the blind holdout supports it (spec section 7).
    split_rule = destination.block_split(inp.block_revenue, classes, payouts=True)
    fresh = holdout_decision(inp.relays, split_rule)
    decision, frozen, recomputed = (
        settle_decision(raw_dir, inp.relays, fresh) if raw_dir else (fresh, False, None)
    )
    # The seed-45 holdout (forwarder spec section 6) decides once frozen; until then the
    # seed-44 decision stays the published one.
    fresh2 = holdout_decision(inp.relays, split_rule, relays.HOLDOUT2_ROUND, inp.payment_paths)
    decision2, frozen2, recomputed2 = (
        settle_decision(
            raw_dir,
            inp.relays,
            fresh2,
            decision_file=HOLDOUT2_DECISION_FILE,
            holdout_file=relays.HOLDOUT2_FILE,
            round_label=relays.HOLDOUT2_ROUND,
            ready=holdout2_ready(raw_dir, split_rule, inp.payment_paths),
        )
        if raw_dir
        else (fresh2, False, None)
    )
    published = decision2 if frozen2 else decision
    one = bool(published["one_split"])
    print("seed-45 holdout: " + _decision_line(decision2, bool(decision2["one_split"]), frozen2))
    print(_decision_line(published, one, frozen2 or frozen))
    split = (
        split_rule if one else destination.block_split(inp.block_revenue, classes, payouts=False)
    )
    costs = destination.searcher_costs(
        inp.aligned, inp.events, inp.blocks, inp.tx_direct, inp.tx_other_logs, split
    )
    dest = destination.destination(steps, inp.aligned, costs, split, sensitivity=not one)
    if not one:  # the rule's own split as a third number; it never replaces the published one
        rule_single = destination.searcher_costs(
            inp.aligned, inp.events, inp.blocks, inp.tx_direct, inp.tx_other_logs, split_rule
        ).filter(pl.col("scope") == destination.SINGLE)
        lvr_searcher = dest["lvr_on_searcher_swaps_usd"]
        proposer = float(rule_single["proposer_usd"].sum())
        margin = float(rule_single["builder_margin_usd"].sum())
        dest["rule_split"] = {
            "proposer_usd": proposer,
            "builder_margin_usd": margin,
            "share_proposer": proposer / lvr_searcher if lvr_searcher else 0.0,
            "share_builder_margin": margin / lvr_searcher if lvr_searcher else 0.0,
            "label": RULE_SPLIT_LABEL,
        }
    totals_dest = {
        k: v for k, v in dest.items() if k not in ("sensitivity_self_built", "rule_split")
    }
    robust, robust_summary, identity, reprice = reference_robustness(
        inp, daily, ref, totals, end_us
    )
    flash_fees = float(
        steps.filter(pl.col("accrued"))
        .join(
            inp.aligned.select("block_number", "log_index"),
            on=["block_number", "log_index"],
            how="anti",
        )["fee_usd"]
        .sum()
    )
    summary["lp"]["robustness"] = robust_summary
    single = costs.filter(pl.col("scope") == destination.SINGLE)
    block_usd = single.group_by("block_number").agg(pl.col("builder_paid_usd").sum())
    class_tbl = destination.class_table(classes, single)
    recipients, n_differ = payouts.recipient_types(classes, inp.payout_code, block_usd)
    reported = [
        check_r1_relays(inp.relays, split_rule, block_usd, inp.payment_paths),
        check_r2_traces_vs_alchemy(inp.tx_direct, inp.bot_transfers, inp.blocks, inp.tx_other_logs),
        check_r3_lp_types(positions),
        check_r4_transferred(data.positions, positions["position_id"].to_list()),
        check_r5_null_12s(run.null_12s_steps, steps),
        check_r6_robustness(identity, flash_fees, totals["fees_minus_lvr_usd"], reprice),
    ]
    dest.update(
        proposer_split="one" if one else "hedge",
        holdout_decision=decision,
        decision_frozen=frozen,
        holdout_decision_2=decision2,
        decision_2_frozen=frozen2,
        published_decision=relays.HOLDOUT2_ROUND if frozen2 else "holdout",
        block_classes=class_tbl.to_dicts(),
        recipient_types=recipients.to_dicts(),
        n_recipients_reads_differ=n_differ,
        n_top_up=payouts.class_counts(classes)["n_top_up"],
    )
    if recomputed is not None:
        dest["holdout_decision_recomputed"] = recomputed
    if recomputed2 is not None:
        dest["holdout_decision_2_recomputed"] = recomputed2
    dest["class_counts_by_n"] = {  # how many blocks each class gets at other pair thresholds
        str(n): payouts.class_counts(payouts.block_classes(inp.block_revenue, inp.last_tx, n))
        for n in (20, 50, 100)
    }
    limitation = destination.LIMITATION_TEXT if one else destination.LIMITATION_TEXT_HEDGE
    summary["lp"]["destination"] = dest
    summary["lp"]["checks"].update({r.name: r.summary for r in reported})
    summary["lp"]["destination_limitation"] = limitation
    blocks_theory = ordered_group_by(int_1s, "block_number").agg(
        pl.col("r2").sum(), pl.col("lvr_theory").sum()
    )

    episode_blocks, episode_cex = figdata.episode_tables(daily, bs, steps, inp.trades)
    jit_block = figdata.jit_block_table(positions, flows_window, inp.aligned, inp.events, steps, bs)

    # Everything is computed: write the checks, then the data and results, summary.json last.
    validate.write_report(
        results + reported, results_dir, provenance, stem="lp_checks", title="LP analysis checks"
    )
    processed_dir.mkdir(parents=True, exist_ok=True)
    write_exact(steps, processed_dir / "swap_steps.parquet")
    write_exact(positions, processed_dir / "positions.parquet")
    write_exact(data.flows, processed_dir / "position_flows.parquet")
    write_exact(days, processed_dir / "position_days.parquet")
    write_exact(blocks_theory, processed_dir / "lp_blocks.parquet")

    out = results_dir
    report.write_markdown(
        out,
        "lp_pnl",
        "LP P&L: fees vs LVR",
        [
            ("Window totals", report.metrics_table(totals)),
            ("Daily series, with day-bootstrap intervals", report.metrics_table(daily_stats)),
            ("By LP type", groups.filter(pl.col("grouping") == "lp_type")),
            ("JIT per swap", report.metrics_table(jit)),
        ],
        notes=[PNL_NOTE, JIT_NOTE],
    )
    report.write_table(daily, out, "lvr_daily", "Daily fees, LVR and theory")
    report.write_markdown(
        out,
        "vol_regimes",
        "Fees vs LVR by volatility regime",
        [("By regime", regime_summary), ("By regime and LP type", regime_groups)],
    )
    report.write_table(groups, out, "lp_groups", "LP P&L by group", [PNL_NOTE])
    write_text_atomic(out / "positions.csv", positions.write_csv())
    report.write_markdown(
        out,
        "lifetime",
        "Lifetime P&L against holding (window-active positions)",
        [
            ("Overall", report.metrics_table(life_overall)),
            ("By range width", life_width),
            ("By lifetime", life_bucket),
        ],
    )
    report.write_markdown(
        out,
        "lvr_destination",
        "Where LVR goes",
        [
            ("Totals", report.metrics_table(totals_dest)),
            ("Block classes", class_tbl),
            ("Payout recipients", recipients),
            ("Seed-45 holdout (R1d)", report.metrics_table(decision2)),
            *(
                []
                if one
                else [
                    (
                        "Sensitivity: self-built blocks at the paid-block proposer share",
                        report.metrics_table(dest["sensitivity_self_built"]),
                    ),
                    (
                        "Payout rule's split (measured payments; not adopted)",
                        report.metrics_table(dest["rule_split"]),
                    ),
                ]
            ),
        ],
        notes=[
            DESTINATION_NOTE,
            classes_note(class_tbl),
            *([] if one else [SENSITIVITY_NOTE]),
            limitation,
        ],
    )
    report.write_table(
        robust, out, "reference_robustness", "Reference and timing robustness", [ROBUSTNESS_NOTE]
    )
    report.write_markdown(
        out,
        "reference_robustness_proxy",
        "Trade-side mid proxy: quality at swap times",
        [("", report.metrics_table(robust_summary["proxy_quality"]))],
    )
    timed = inp.block_timing.filter(pl.col("found"))
    write_text_atomic(out / "block_timing.csv", timed.write_csv())
    report.write_markdown(
        out,
        "block_timing",
        "When blocks were sealed: winning-bid times",
        [
            (
                "Pooled",
                report.metrics_table(
                    {k: v for k, v in robust_summary["timing"].items() if k != "by_relay"}
                ),
            ),
            ("By relay", pl.DataFrame(robust_summary["timing"]["by_relay"])),
        ],
        notes=[TIMING_NOTE],
    )
    fig_data = out / "figure_data"
    fig_data.mkdir(parents=True, exist_ok=True)
    write_text_atomic(fig_data / "episode_blocks.csv", episode_blocks.write_csv())
    write_text_atomic(fig_data / "episode_cex.csv", episode_cex.write_csv())
    write_text_atomic(fig_data / "jit_block.csv", jit_block.write_csv())
    report.write_summary(summary, out)
    return status


def run_lp() -> str:
    validate.require_validated()
    _need(config.RESULTS_DIR / "summary.json", "analyze")  # fail before the long replay
    inp = load_lp_inputs(
        config.RAW_DIR, config.INTERIM_DIR, config.PROCESSED_DIR, config.LP_LABELS_CSV
    )
    provenance = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": validate.git_commit(),
    }
    return lp_analysis(
        inp, config.RESULTS_DIR, config.PROCESSED_DIR, provenance, raw_dir=config.RAW_DIR
    )
