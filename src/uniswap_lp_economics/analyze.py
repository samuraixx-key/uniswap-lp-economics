"""`ulpe analyze`: validated data -> results/ (analysis checks, tables, charts, summary.json)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics import (
    align,
    arbprofit,
    checks,
    config,
    discovery,
    figures,
    flows,
    markouts,
    report,
    validate,
)
from uniswap_lp_economics.build import load_snapshot_meta
from uniswap_lp_economics.data import blocks as bq_blocks
from uniswap_lp_economics.data import transfers
from uniswap_lp_economics.io import read_exact, write_exact, write_text_atomic
from uniswap_lp_economics.lp import swapfees
from uniswap_lp_economics.tickbook import TickBook

MARKOUT_NOTE = (
    "Trader side, after the 0.05% swap fee: "
    "markout = -(amount_usdc + amount_eth x P_binance(t0 + h)), "
    "t0 = block timestamp, P = last Binance ETHUSDC trade at or before that time. "
    "Positive = the swap won against the pool at that horizon. "
    "mean_bp is notional-weighted (sum markout / sum notional); "
    "ci = 95% bootstrap over UTC days (1,000 resamples, seed 42)."
)
FIGURES = {
    "markouts": "1_markouts_by_flow.png",
    "basis": "2_basis_histogram.png",
    "episodes": "3_gap_episodes.png",
    "waterfall": "4_arbitrage_waterfall.png",
    "leadlag": "5_lead_lag.png",
    "bots": "6_bot_gross_vs_kept.png",
}


@dataclass
class Inputs:
    events: pl.DataFrame
    swaps: pl.DataFrame
    trades: pl.DataFrame
    klines: pl.DataFrame
    ticks: pl.DataFrame
    meta: dict[str, int]
    blocks: pl.DataFrame
    other_logs: pl.DataFrame
    transfers: pl.DataFrame
    labels: pl.DataFrame
    bots: list[str]


def _need(path: Path, command: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `ulpe {command}` first")
    return path


def load_inputs(raw: Path, interim: Path, labels_csv: Path) -> Inputs:
    swaps = read_exact(_need(interim / "swaps.parquet", "build"))
    labels = flows.load_labels(labels_csv)
    bots = flows.top_bots(flows.label_swaps(swaps, labels))
    _need(raw / bq_blocks.BLOCKS_FILE, "fetch-blocks")
    if not bq_blocks.bot_tx_logs_current(raw, bots):
        raise FileNotFoundError(
            "top-bot transaction logs are missing or were fetched for other bots; "
            "run `ulpe fetch-blocks`"
        )
    return Inputs(
        events=read_exact(_need(interim / "events.parquet", "build")),
        swaps=swaps,
        trades=pl.read_parquet(_need(interim / "cex_ethusdc.parquet", "build")),
        klines=pl.read_parquet(_need(interim / "cex_ethusdt_1s.parquet", "build")),
        ticks=read_exact(_need(raw / "tickbook_snapshot.parquet", "fetch-snapshot")),
        meta=load_snapshot_meta(raw),
        blocks=pl.read_parquet(raw / bq_blocks.BLOCKS_FILE),
        other_logs=pl.read_parquet(raw / bq_blocks.OTHER_LOGS_FILE),
        transfers=transfers.load_bot_transfers(raw, bots),
        labels=labels,
        bots=bots,
    )


def analysis_input_hashes(raw: Path, interim: Path, labels_csv: Path) -> dict[str, str]:
    files = [
        *sorted(interim.glob("*.parquet")),
        raw / "tickbook_snapshot.parquet",
        raw / "snapshot_meta.json",
        raw / bq_blocks.BLOCKS_FILE,
        raw / bq_blocks.OTHER_LOGS_FILE,
        *sorted((raw / transfers.TRANSFERS_DIR).glob("*.parquet")),
    ]
    hashes = {p.relative_to(raw.parent).as_posix(): validate.file_hash(p) for p in files}
    hashes[f"labels/{labels_csv.name}"] = validate.file_hash(labels_csv)
    return hashes


def build_aligned(
    labelled: pl.DataFrame,
    ref: pl.DataFrame,
    end_us: int,
    inp: Inputs,
    swap_fees: pl.DataFrame,
    shift_s: float = 0.0,
) -> pl.DataFrame:
    """One row per swap: reference prices, markouts and costs (plan Ruling 5)."""
    fees = swap_fees.select("block_number", "log_index", "protocol_fee_raw")
    a = labelled.join(fees, on=["block_number", "log_index"], how="left", maintain_order="left")
    a = align.add_reference_prices(a, ref, end_us, shift_s=shift_s)
    a = markouts.add_markouts(a)
    scope = arbprofit.tx_scope(inp.other_logs)
    return arbprofit.add_costs(a, inp.blocks, inp.transfers, scope, inp.bots)


def analyze(
    inp: Inputs,
    results_dir: Path,
    processed_dir: Path,
    provenance: dict[str, Any],
    end_us: int | None = None,
    blocks_end_us: int | None = None,
) -> str:
    end_us = align.window_end_us() if end_us is None else end_us
    window_end = align.window_end_us() if blocks_end_us is None else blocks_end_us
    labelled = flows.label_swaps(inp.swaps, inp.labels)
    ref = align.reference_table(inp.trades)
    fee_protocol = int(inp.meta["fee_protocol"])
    swap_fees = swapfees.build_swap_fees(
        inp.events, TickBook.from_snapshot(inp.ticks, inp.meta), fee_protocol
    )
    aligned = build_aligned(labelled, ref, end_us, inp, swap_fees)
    series = discovery.build_block_series(
        inp.events,
        TickBook.from_snapshot(inp.ticks, inp.meta),
        fee_protocol,
        inp.blocks,
        ref,
        end_us,
    )
    results = [
        checks.check_a1(inp.events, TickBook.from_snapshot(inp.ticks, inp.meta), fee_protocol),
        checks.check_a2(series, inp.blocks, inp.events, int(inp.meta["block"]) + 1, window_end),
        checks.check_a3(aligned),
        checks.check_a4(aligned, int(ref["ts_us"].min()), end_us),  # type: ignore[arg-type]
        checks.check_a5(labelled),
        checks.check_a6(inp.transfers, aligned, inp.blocks),
    ]
    status = checks.write_checks(results, results_dir, provenance)
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.name}: {r.summary}")
    if status != "PASS":
        return status
    processed_dir.mkdir(parents=True, exist_ok=True)
    write_exact(aligned, processed_dir / "aligned.parquet")
    write_exact(series, processed_dir / "blocks_state.parquet")
    write_exact(swap_fees, processed_dir / "swap_fees.parquet")
    _write_results(inp, labelled, aligned, series, ref, swap_fees, end_us, results_dir, provenance)
    return status


def _write_results(
    inp: Inputs,
    labelled: pl.DataFrame,
    aligned: pl.DataFrame,
    series: pl.DataFrame,
    ref: pl.DataFrame,
    swap_fees: pl.DataFrame,
    end_us: int,
    out: Path,
    provenance: dict[str, Any],
) -> None:
    figs = out / "figures"

    # Markouts (spec 5) and robustness.
    tables = markouts.markout_tables(aligned)
    report.write_table(tables, out, "markouts", "Trader markouts vs Binance", [MARKOUT_NOTE])
    by_label = tables.filter(pl.col("grouping") == "flow_label")
    variants = {
        "primary": aligned,
        "ethusdt_reference": build_aligned(
            labelled, align.kline_reference_table(inp.klines), end_us, inp, swap_fees
        ),
        "t0_minus_2s": build_aligned(labelled, ref, end_us, inp, swap_fees, shift_s=-2.0),
        "exclude_stale_over_5s": markouts.exclude_stale(aligned),
    }
    robustness = pl.concat(
        [
            markouts.markout_table(df, ["flow_label"]).with_columns(variant=pl.lit(name))
            for name, df in variants.items()
        ]
    ).select("variant", pl.exclude("variant"))
    report.write_table(
        robustness, out, "markouts_robustness", "Markout robustness by flow label", [MARKOUT_NOTE]
    )
    figures.markout_curves(by_label, figs / FIGURES["markouts"])

    # Labels.
    coverage = flows.label_coverage(labelled)
    report.write_markdown(
        out,
        "labels_coverage",
        "Flow label coverage",
        [
            ("Notional by label", coverage),
            ("Top unlabelled pool callers (sender)", flows.top_unlabelled(labelled, "sender")),
            (
                "Top unlabelled transaction targets (to_address)",
                flows.top_unlabelled(labelled, "to_address"),
            ),
        ],
    )

    # Price discovery (spec 6).
    basis = discovery.basis_stats(series)
    report.write_markdown(
        out, "basis", "Pool vs Binance basis", [("", report.metrics_table(basis))]
    )
    figures.basis_histogram(series, figs / FIGURES["basis"], discovery.FEE_BAND_BP)
    episodes = {
        k: discovery.find_episodes(series, labelled, k) for k in discovery.EPISODE_THRESHOLDS_BP
    }
    summaries = {k: discovery.episode_summary(e) for k, e in episodes.items()}
    all_episodes = pl.concat(
        [e.with_columns(threshold_bp=pl.lit(k)) for k, e in episodes.items()],
        how="vertical_relaxed",
    )
    write_text_atomic(out / "episodes.csv", all_episodes.write_csv())
    report.write_markdown(
        out,
        "episodes",
        "Gap episodes and who closes them",
        [(f"|basis| > {k:g} bp", s) for k, s in summaries.items()],
    )
    primary_k = discovery.EPISODE_THRESHOLDS_BP[0]
    figures.episode_chart(episodes[primary_k], summaries[primary_k], figs / FIGURES["episodes"])
    xc = discovery.cross_correlation(series)
    ar1 = discovery.ar1_half_life(series)
    report.write_markdown(
        out,
        "leadlag",
        "Lead-lag",
        [
            ("Cross-correlation (positive lag = Binance first)", xc),
            ("AR(1) basis", report.metrics_table(ar1)),
        ],
        digits=4,
    )
    figures.cross_correlation_chart(xc, figs / FIGURES["leadlag"])

    # Available vs captured vs kept (spec 5.5, 6.5).
    w = arbprofit.waterfall(series, aligned)
    ratios = {
        "captured_over_available": (
            w["captured_searchers_usd"] / w["available_usd"] if w["available_usd"] else None
        ),
        "kept_over_top_bot_gross": (
            w["kept_usd"] / w["top_bot_single_pool_gross_usd"]
            if w["top_bot_single_pool_gross_usd"]
            else None
        ),
        "kept_over_top_bot_gross_12s": (
            w["kept_12s_usd"] / w["top_bot_single_pool_gross_12s_usd"]
            if w["top_bot_single_pool_gross_12s_usd"]
            else None
        ),
    }
    daily = discovery.available_vs_captured(series, aligned)
    report.write_markdown(
        out,
        "arbitrage",
        "Arbitrage: available, captured, kept",
        [("Totals", report.metrics_table({**w, **ratios})), ("By day", daily)],
        notes=[report.LIMITATION_TEXT],
    )
    figures.waterfall_chart(w, figs / FIGURES["waterfall"])
    bot_profit = arbprofit.bot_profit_table(aligned)
    report.write_table(
        bot_profit, out, "bot_profit", "Top bots: gross vs kept", [report.LIMITATION_TEXT]
    )
    figures.bot_profit_chart(bot_profit, figs / FIGURES["bots"])

    total = bot_profit.filter(pl.col("sender") == "TOTAL").to_dicts()
    report.write_summary(
        {
            **provenance,
            "window": f"[{config.WINDOW_START}, {config.WINDOW_END})",
            "swaps": aligned.height,
            "notional_usd": float(aligned["notional_usd"].sum()),
            "top_bots": inp.bots,
            "markouts_all": tables.filter(pl.col("grouping") == "all").to_dicts(),
            "markouts_by_label": by_label.to_dicts(),
            "markouts_robustness_0s": robustness.filter(pl.col("horizon_s") == 0).to_dicts(),
            "markouts_by_label_x_size_0s": tables.filter(
                (pl.col("grouping") == "flow_label_x_size") & (pl.col("horizon_s") == 0)
            ).to_dicts(),
            "basis": basis,
            "episodes": {f"{k:g}bp": s.to_dicts() for k, s in summaries.items()},
            "episode_counts": {f"{k:g}bp": e.height for k, e in episodes.items()},
            "lead_lag": {"cross_correlation": xc.to_dicts(), "ar1": ar1},
            "arbitrage": {**w, **ratios},
            "bot_profit_total": total[0] if total else None,
            "label_coverage": coverage.to_dicts(),
            "limitation": report.LIMITATION_TEXT,
        },
        out,
    )


def run_analysis() -> str:
    validate.require_validated()
    inp = load_inputs(config.RAW_DIR, config.INTERIM_DIR, config.LABELS_CSV)
    provenance = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": validate.git_commit(),
        "input_sha256_16": analysis_input_hashes(
            config.RAW_DIR, config.INTERIM_DIR, config.LABELS_CSV
        ),
    }
    return analyze(inp, config.RESULTS_DIR, config.PROCESSED_DIR, provenance)
