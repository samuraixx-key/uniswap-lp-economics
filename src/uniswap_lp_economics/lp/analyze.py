"""`ulpe lp`: validated data -> LP results (checks L1-L7, tables, charts, summary.json["lp"])."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics import align, config, flows, report, validate
from uniswap_lp_economics.build import load_snapshot_meta
from uniswap_lp_economics.data import (
    binance,
    builders,
    chain_state,
    history,
    relays,
    transfers,
)
from uniswap_lp_economics.data import blocks as bq_blocks
from uniswap_lp_economics.io import read_exact, write_exact, write_text_atomic
from uniswap_lp_economics.lp import destination, figdata, lifetime, pnl, theory
from uniswap_lp_economics.lp.checks import (
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
SENSITIVITY_NOTE = (
    "The primary split treats a block whose last transaction is not from its fee recipient as "
    "self-built (proposer share 1). The relay sample shows that most such blocks are MEV-Boost "
    "blocks that paid the proposer some other way, so the sensitivity gives those blocks the "
    "volume-weighted proposer share of the paid blocks instead. Only proposer and builder margin "
    "move; their sum, and every other figure, is the same under both."
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
    lp_labels: pl.DataFrame
    blocks: pl.DataFrame
    block_revenue: pl.DataFrame
    tx_direct: pl.DataFrame
    tx_other_logs: pl.DataFrame
    relays: pl.DataFrame
    bot_transfers: pl.DataFrame


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
        lp_labels=pnl.load_lp_labels(lp_labels_csv),
        blocks=pl.read_parquet(_need(raw / bq_blocks.BLOCKS_FILE, "fetch-blocks")),
        block_revenue=block_revenue,
        tx_direct=tx_direct,
        tx_other_logs=tx_other_logs,
        relays=read_exact(_need(raw / relays.RELAY_FILE, "fetch-relays")),  # wei: Int128
        bot_transfers=transfers.load_bot_transfers(raw, top_bots),
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


def lp_analysis(
    inp: LpInputs,
    results_dir: Path,
    processed_dir: Path,
    provenance: dict[str, Any],
    end_us: int | None = None,
) -> str:
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
    split = destination.block_split(inp.block_revenue)
    costs = destination.searcher_costs(
        inp.aligned, inp.events, inp.blocks, inp.tx_direct, inp.tx_other_logs, split
    )
    dest = destination.destination(steps, inp.aligned, costs, split)
    reported = [
        check_r1_relays(inp.relays, split),
        check_r2_traces_vs_alchemy(inp.tx_direct, inp.bot_transfers, inp.blocks, inp.tx_other_logs),
        check_r3_lp_types(positions),
        check_r4_transferred(data.positions, positions["position_id"].to_list()),
        check_r5_null_12s(run.null_12s_steps, steps),
    ]
    summary["lp"]["destination"] = dest
    summary["lp"]["checks"].update({r.name: r.summary for r in reported})
    summary["lp"]["destination_limitation"] = destination.LIMITATION_TEXT
    blocks_theory = int_1s.group_by("block_number").agg(
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
            (
                "Totals (primary split)",
                report.metrics_table(
                    {k: v for k, v in dest.items() if k != "sensitivity_self_built"}
                ),
            ),
            (
                "Sensitivity: self-built blocks at the paid-block proposer share",
                report.metrics_table(dest["sensitivity_self_built"]),
            ),
        ],
        notes=[DESTINATION_NOTE, SENSITIVITY_NOTE, destination.LIMITATION_TEXT],
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
    return lp_analysis(inp, config.RESULTS_DIR, config.PROCESSED_DIR, provenance)
