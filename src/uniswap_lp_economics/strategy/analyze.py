"""`ulpe strategy`: gates S1/S2, the July freeze, then the August-September report (spec 4, 7, 9).

Two runs. With no freeze file the run computes July only (choices, delta, calibration) and writes
`results/strategy_freeze.json`; with the freeze it computes the report period with every July
value taken from the file, which it never rewrites.
"""

import json
import math
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics import config, report, validate
from uniswap_lp_economics.align import window_end_us
from uniswap_lp_economics.config import US
from uniswap_lp_economics.data import blocks as bq_blocks
from uniswap_lp_economics.data import builders, futures
from uniswap_lp_economics.io import read_exact, write_text_atomic
from uniswap_lp_economics.lp.analyze import LpInputs, hourly_grid, load_lp_inputs
from uniswap_lp_economics.strategy import checks, stats
from uniswap_lp_economics.strategy.cfpool import (
    CfInputs,
    FeeRule,
    FixedFee,
    OracleFee,
    prepare_inputs,
    rule_grid,
    run_pool,
)
from uniswap_lp_economics.strategy.checks import (
    check_s1,
    check_s2,
    check_s3,
    replaced_keys,
    sandwich_legs,
)
from uniswap_lp_economics.strategy.hedge import hedge_table, position_path
from uniswap_lp_economics.strategy.params import (
    BASELINE_FEE_BP,
    FEE_LEVELS_BP,
    FULL_RANGE,
    HALF_WIDTHS_BP,
    JULY_START_US,
    PEAK_SHARE_FLAG,
    PRIMARY_CAPITAL,
    REPORT_END_US,
    REPORT_START_US,
    RULES,
    TAKER_FEE_BP,
    TAKER_FEE_SENSITIVITY_BP,
    TESTED_RULES,
    bp_to_pips,
)
from uniswap_lp_economics.strategy.ranges import (
    STRATEGY_COLUMNS,
    LpCosts,
    StrategyResult,
    lp_costs,
    peak_share,
    score,
    segments,
)
from uniswap_lp_economics.validate import CheckResult

PREREG_TAG = "strategy-preregistered"
FREEZE_FILE = "strategy_freeze.json"
DEFAULT_WORKERS = 4  # plan Ruling 9: a fee run peaks at ~1.35 GB, 4 fit in 16 GB
COUNTERFACTUAL_NOTE = (
    "Counterfactual: holds other traders' behaviour fixed; they would react to a different "
    "range, fee or hedge."
)
FEE_NOTE = (
    "Fixed-volume shortcut: kept (non-arbitrage) flow is re-executed at its observed size at "
    "every fee. break_even_share beside each row is the share of that flow the pool could lose "
    "before the full-range LP is no better off than at 5 bp (removed flow's fees and LVR scale "
    "linearly; the price path does not change). The test (verdict) is on the arbitrage side "
    "only: arb_ratio and d_arb against the 5 bp model run, paired day bootstrap. bp_per_day of a "
    "fee rule: (fees - LVR) per unit of liquidity times the liquidity of the $1M full-range "
    "position, over that position's value in the real pool."
)
MODEL_ONLY_NOTE = (
    "Model-only: calibration (S3) failed in July, so every fee result here is model-only and the "
    "fee test is not tested."
)
_FREEZE_KEYS = (
    "delta",
    "r0",
    "min_profit_gas",
    "calibration",
    "best_strategy",
    "lp_costs",
    "input_hashes",
)
_PL = ("fee_arb_pl", "lvr_arb_pl", "fee_kept_pl", "lvr_kept_pl")
_D_COLUMNS = ("d_ratio", "d_lo", "d_hi", "n_undefined", "inside", "above")


@dataclass
class StrategyExtras:
    positions: pl.DataFrame
    position_flows: pl.DataFrame
    swap_steps: pl.DataFrame
    funding: pl.DataFrame
    perp: pl.DataFrame


# --- the freeze (spec 4; Review Focus 5) ---


def write_freeze(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(
            f"{path} exists: the July freeze is written once (delete it by hand to re-run July)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)  # a NaN fails here
    write_text_atomic(path, text + "\n")


def read_freeze(path: Path, hashes: dict[str, str]) -> dict[str, Any]:
    """The frozen July values; stops (never writes) if the file is unreadable or was frozen on
    other inputs."""
    keep = "it is never rewritten: restore it, or delete it by hand to re-run July"
    try:
        frozen = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"{path} cannot be read ({e}); {keep}") from None
    if not isinstance(frozen, dict):
        raise SystemExit(f"{path} is not a JSON object; {keep}")
    if missing := [k for k in _FREEZE_KEYS if k not in frozen]:
        raise SystemExit(f"{path} lacks {missing}; {keep}")
    got = frozen["input_hashes"]
    if got != hashes:
        known = got if isinstance(got, dict) else {}
        changed = sorted(k for k in known.keys() | hashes.keys() if known.get(k) != hashes.get(k))
        raise SystemExit(
            f"{path} was frozen on other inputs ({', '.join(changed[:5]) or 'input_hashes'} "
            f"differ); {keep}"
        )
    return frozen


# --- fee runs (spec 6.5), in worker processes ---

_CI: CfInputs | None = None
FeeRuns = dict[tuple[str, float], tuple[pl.DataFrame, dict[str, int]]]


def _init_worker(ci: CfInputs | None) -> None:
    global _CI
    _CI = ci


def _fee_run(job: tuple[FeeRule, float, int]) -> tuple[pl.DataFrame, dict[str, int]]:
    rule, offset, gas = job
    assert _CI is not None
    r = run_pool(_CI, rule, replace=True, ref_offset_s=offset, min_profit_gas=gas)
    return r.daily, r.counts


def fee_runs(ci: CfInputs, min_profit_gas: int, workers: int = DEFAULT_WORKERS) -> FeeRuns:
    """Every rule of rule_grid at the 0 s reference and the fixed levels at +1 s, each over the
    whole window from the snapshot; (rule name, offset) -> (daily, counts). `workers` 1 runs
    in-process; otherwise each worker receives `ci` once."""
    jobs: list[tuple[FeeRule, float, int]] = [(r, 0.0, min_profit_gas) for r in rule_grid()] + [
        (FixedFee(bp_to_pips(bp)), 1.0, min_profit_gas) for bp in FEE_LEVELS_BP
    ]
    if workers == 1:
        _init_worker(ci)
        try:
            out = [_fee_run(j) for j in jobs]
        finally:
            _init_worker(None)
    else:
        # spawn, not Linux's default fork: forking after polars starts its threads deadlocks
        spawn = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            workers, mp_context=spawn, initializer=_init_worker, initargs=(ci,)
        ) as ex:
            out = list(ex.map(_fee_run, jobs))
    return {(rule.name, off): o for (rule, off, _), o in zip(jobs, out, strict=True)}


# --- range cells (spec 5) ---


@dataclass(frozen=True)
class Period:
    start_us: int
    end_us: int
    first: int  # first and last block of the period
    last: int
    first_ts_us: int
    days: list[date]


def _date(us: int) -> date:
    return datetime.fromtimestamp(us // US, UTC).date()


def period(starts: pl.DataFrame, start_us: int, end_us: int) -> Period:
    b = starts.filter(pl.col("ts_us").is_between(start_us, end_us, closed="left"))
    if b.height == 0:
        raise ValueError(f"no block in [{start_us}, {end_us})")
    days = pl.date_range(_date(start_us), _date(end_us - 1), eager=True).to_list()
    first, last, ts = b.select(
        first=pl.col("block_number").min(),
        last=pl.col("block_number").max(),
        ts=pl.col("ts_us").min(),
    ).row(0)
    return Period(start_us, end_us, first, last, ts, days)


def _cells() -> dict[str, tuple[str, int | None]]:
    return {
        FULL_RANGE: (FULL_RANGE, None),
        **{f"{rule}_{w}bp": (rule, w) for rule in RULES for w in HALF_WIDTHS_BP},
    }


def range_cells(
    steps: pl.DataFrame, starts: pl.DataFrame, grid: pl.DataFrame, costs: LpCosts, p: Period
) -> dict[str, StrategyResult]:
    """Every grid strategy and full range, with fresh $1M at the period's first block."""
    s = steps.filter(pl.col("block_number").is_between(p.first, p.last))
    return {
        name: score(
            s,
            segments(rule, w, starts, p.first, p.last),
            starts,
            grid,
            PRIMARY_CAPITAL,
            costs,
            TAKER_FEE_BP,
            p.days,
        )
        for name, (rule, w) in _cells().items()
    }


def _ratio(num: float, den: float) -> float:
    return num / den if den > 0 else math.nan


def range_row(name: str, r: StrategyResult, scale: float = 1.0) -> dict[str, Any]:
    """STRATEGY_COLUMNS (and the taker-fee variants) at `scale` x $1M: fees, LVR, trade and value
    scale with size, gas does not (Task 5)."""
    rule, w = _cells()[name]
    d = r.daily
    fee, lvr, trade, twv = (
        scale * float(d[c].sum()) for c in ("fee_usd", "lvr_usd", "trade_usd", "twv_usd")
    )
    gas = float(d["gas_usd"].sum())

    def bp(taker_bp: float) -> float:
        net = fee - lvr - gas - trade * taker_bp / TAKER_FEE_BP
        return net / twv * 1e4 if twv > 0 else math.nan

    n_blocks = int(d["n_blocks"].sum())
    share = peak_share(r.peak_ratio, scale)
    return {
        "strategy": name,
        "rule": rule,
        "half_width_bp": w,
        "capital": PRIMARY_CAPITAL * scale,
        "fees_over_lvr": _ratio(fee, lvr),
        "bp_per_day": bp(TAKER_FEE_BP),
        "recentres": int(d["recentres"].sum()),
        "gas_usd": gas,
        "trade_usd": trade,
        "in_range_share": int(d["in_range_blocks"].sum()) / n_blocks if n_blocks else math.nan,
        "days_in_range": int((d["in_range_blocks"] > 0).sum()),
        "peak_share": share,
        "flagged": share > PEAK_SHARE_FLAG,
        "counted": rule in TESTED_RULES and scale == 1.0,
        **{f"bp_per_day_taker_{t:g}bp": bp(t) for t in TAKER_FEE_SENSITIVITY_BP},
    }


# --- the two runs ---


def strategy_analysis(
    inp: LpInputs,
    extra: StrategyExtras,
    results_dir: Path,
    processed_dir: Path,
    provenance: dict[str, Any],
    split_us: int = REPORT_START_US,
    end_us: int | None = None,
    workers: int | None = None,
) -> str:
    """ "FROZEN" (first run, July), "PASS" (report run) or "FAIL" (a gate failed). `provenance`
    carries `input_hashes`, which the freeze records and the report run must match.
    `processed_dir` is kept for symmetry with lp_analysis: this step writes no processed data."""
    end_us = window_end_us() if end_us is None else end_us
    if "input_hashes" not in provenance:
        raise ValueError("provenance needs input_hashes: the freeze is checked against them")
    hashes: dict[str, str] = provenance["input_hashes"]
    meta = {k: v for k, v in provenance.items() if k != "input_hashes"}
    freeze_path = results_dir / FREEZE_FILE
    frozen = read_freeze(freeze_path, hashes) if freeze_path.exists() else None
    snap = int(inp.meta["block"])
    replaced = replaced_keys(inp.aligned, inp.tx_other_logs)
    ci = prepare_inputs(
        inp.events,
        inp.ticks,
        inp.meta,
        inp.aligned,
        inp.swap_fees,
        inp.blocks_state,
        inp.blocks,
        inp.trades,
        replaced,
        end_us,
    )
    identity = run_pool(ci, FixedFee(bp_to_pips(BASELINE_FEE_BP)), replace=False, keep_steps=True)
    assert identity.steps is not None
    gates = [
        check_s2(identity, extra.swap_steps, inp.blocks_state, inp.aligned),
        check_s1(identity.steps, extra.positions, extra.position_flows, snap),
    ]
    for g in gates:
        print(f"{'PASS' if g.passed else 'FAIL'}  {g.name}: {g.summary}")
    if not all(g.passed for g in gates):
        validate.write_report(
            gates, results_dir, meta, stem="strategy_checks", title="Strategy checks"
        )
        return "FAIL"
    starts = inp.blocks_state.select("block_number", "ts_us", "tick", "sqrt_price_x96").join(
        ci.blocks.select("block_number", "day", "p_ref_0", "base_fee_wei"),
        on="block_number",
        how="left",
        maintain_order="left",
    )
    if frozen is None:
        # Ruling 12: gas medians from July transactions only, frozen for the report run
        window = pl.col("block_number") > snap
        july_tx = pl.col("block_timestamp").dt.epoch("us") < split_us
        costs = lp_costs(inp.events.filter(window & july_tx), inp.blocks)
        july = period(starts, JULY_START_US, split_us)
        grid = hourly_grid(inp.blocks_state, july.first_ts_us, split_us)
        cells = range_cells(identity.steps, starts, grid, costs, july)
        payload, results = _july(inp, extra, cells, replaced, split_us)
        payload["lp_costs"] = asdict(costs)
        validate.write_report(
            gates + results, results_dir, meta, stem="strategy_checks", title="Strategy checks"
        )
        write_freeze(freeze_path, {**payload, **meta, "input_hashes": hashes})
        print(
            f"July frozen: commit results/{FREEZE_FILE}, tag it {PREREG_TAG}, "
            "then run ulpe strategy again"
        )
        return "FROZEN"
    # Report run: read summary.json now, so a missing one stops before anything is written.
    summary = json.loads((results_dir / "summary.json").read_text(encoding="utf-8"))
    costs = LpCosts(**frozen["lp_costs"])
    rep = period(starts, split_us, REPORT_END_US)
    grid = hourly_grid(inp.blocks_state, rep.first_ts_us, REPORT_END_US)
    cells = range_cells(identity.steps, starts, grid, costs, rep)
    runs = fee_runs(
        ci, int(frozen["min_profit_gas"]), DEFAULT_WORKERS if workers is None else workers
    )
    real = _real_pool(identity.daily, identity.steps, replaced, rep)
    out = _report(frozen, cells, runs, real, rep)
    best = frozen["best_strategy"]["strategy"]
    hedge = pl.concat(
        _hedge(name, cells[name], starts, extra, rep) for name in dict.fromkeys((FULL_RANGE, best))
    )
    flagged = out["ranges"].filter(pl.col("flagged"))
    counts = [{"rule": n, "ref_offset_s": o, **c} for (n, o), (_, c) in runs.items()]
    reported = [
        CheckResult(
            "S3 calibration (July, frozen)",
            bool(frozen["calibration"]["passed"]),
            frozen["calibration"],
            reported=True,
        ),
        CheckResult(
            "Size flags (peak share of active liquidity above 5%)",
            True,
            {
                "flagged_rows": flagged.height,
                "max_peak_share_1m": out["ranges"]
                .filter(pl.col("capital") == PRIMARY_CAPITAL)["peak_share"]
                .max(),
            },
            flagged.select("strategy", "capital", "peak_share").to_dicts(),
            reported=True,
        ),
        CheckResult(
            "Sandwich legs among replaced swaps",
            True,
            sandwich_legs(inp.aligned, replaced),
            reported=True,
        ),
        CheckResult(
            "Counterfactual pool counts",
            True,
            {"runs": len(runs), "july_runs": frozen.get("cfpool_counts")},
            counts,
            reported=True,
        ),
    ]
    summary["strategy"] = {
        **meta,
        **out["test"],
        "min_profit_gas": frozen["min_profit_gas"],
        "calibration": frozen["calibration"],
        "best_strategy": frozen["best_strategy"],
        "real_pool": real,
        "checks": {r.name: r.summary for r in gates + reported},
        "cfpool_counts": counts,
    }

    # Everything is computed: write the checks, the tables, figure data, summary.json last.
    validate.write_report(
        gates + reported, results_dir, meta, stem="strategy_checks", title="Strategy checks"
    )
    fee_notes = [COUNTERFACTUAL_NOTE, FEE_NOTE] + (
        [] if frozen["calibration"]["passed"] else [MODEL_ONLY_NOTE]
    )
    ranges, fees = out["ranges"], out["fees"]
    tables = {"strategy_ranges": ranges, "strategy_fees": fees, "strategy_hedge": hedge}
    one = pl.col("capital") == PRIMARY_CAPITAL
    sections = {
        "strategy_ranges": (
            "Range and rebalancing strategies (August-September, price-taker positions)",
            [
                (
                    "Tested: re-centring cells at $1M, paired against full range",
                    ranges.filter(pl.col("counted")),
                ),
                (
                    "Full range at $1M (the baseline)",
                    ranges.filter(one & (pl.col("rule") == FULL_RANGE)),
                ),
                (
                    "Static ranges at $1M: descriptive, not part of the test",
                    ranges.filter(one & (pl.col("rule") == "static")),
                ),
                ("$100k sensitivity", ranges.filter(~one)),
            ],
            [COUNTERFACTUAL_NOTE],
        ),
        "strategy_fees": (
            "Fee level, dynamic fee and protocol cut (August-September)",
            [("", fees)],
            fee_notes,
        ),
        "strategy_hedge": (
            "Perp delta hedge: the risk lever (August-September, $1M)",
            [("", hedge)],
            [COUNTERFACTUAL_NOTE, "The hedge changes the spread of daily P&L, not fees - LVR."],
        ),
    }
    fig = results_dir / "figure_data"
    fig.mkdir(parents=True, exist_ok=True)
    for stem, df in tables.items():
        title, secs, notes = sections[stem]
        csv = df.write_csv()
        write_text_atomic(results_dir / f"{stem}.csv", csv)
        report.write_markdown(results_dir, stem, title, secs, notes, digits=4)
        write_text_atomic(fig / f"{stem}.csv", csv)
    report.write_markdown(
        results_dir,
        "strategy_test",
        "Pre-registered test (August-September)",
        [("Verdicts", report.metrics_table(out["test"]))],
        [COUNTERFACTUAL_NOTE] + ([] if frozen["calibration"]["passed"] else [MODEL_ONLY_NOTE]),
    )
    report.write_summary(summary, results_dir)
    return "PASS"


def _july(
    inp: LpInputs,
    extra: StrategyExtras,
    cells: dict[str, StrategyResult],
    replaced: set[tuple[int, int]],
    split_us: int,
) -> tuple[dict[str, Any], list[CheckResult]]:
    """The freeze payload (spec 4) and the July checks; nothing past `split_us` is read by a
    counterfactual run."""
    rows = {name: range_row(name, r) for name, r in cells.items()}
    r0 = rows[FULL_RANGE]["fees_over_lvr"]
    delta = stats.delta_from(r0)
    gas = checks.min_profit_gas(inp.aligned, replaced, end_us=split_us)
    ci = prepare_inputs(
        inp.events.filter(pl.col("block_timestamp").dt.epoch("us") < split_us),
        inp.ticks,
        inp.meta,
        inp.aligned,
        inp.swap_fees,
        inp.blocks_state.filter(pl.col("ts_us") < split_us),
        inp.blocks,
        inp.trades,
        replaced,
        split_us,
    )
    five = FixedFee(bp_to_pips(BASELINE_FEE_BP))
    model = run_pool(ci, five, replace=True, ref_offset_s=0.0, min_profit_gas=gas)
    sens = run_pool(ci, five, replace=True, ref_offset_s=1.0, min_profit_gas=gas)
    s3 = check_s3(model, extra.swap_steps, inp.aligned, inp.swap_fees, replaced, sens, split_us)
    tested = [
        r for r in rows.values() if r["rule"] in TESTED_RULES and not math.isnan(r["bp_per_day"])
    ]
    if not tested:
        raise ValueError("no re-centring cell has a July return: no best strategy to freeze")
    best = max(tested, key=lambda r: r["bp_per_day"])
    counts = {"model_0s": model.counts, "model_1s": sens.counts}
    payload = {
        "delta": delta,
        "r0": r0,
        "min_profit_gas": gas,
        "calibration": {"passed": s3.passed, **s3.summary},
        "best_strategy": {k: best[k] for k in ("strategy", "rule", "half_width_bp", "bp_per_day")},
        "cfpool_counts": counts,
    }
    count_check = CheckResult("Counterfactual pool counts (July)", True, counts, reported=True)
    return payload, [s3, count_check]


def _real_pool(
    daily: pl.DataFrame, steps: pl.DataFrame, replaced: set[tuple[int, int]], p: Period
) -> dict[str, float]:
    """The real pool's ratios over the period: whole pool from the identity run, the arbitrage
    side from the replaced swaps' steps."""
    d = stats.on_grid(daily, p.days, ["fee_kept_pl", "lvr_kept_pl"])
    keys = pl.DataFrame(
        sorted(replaced), schema={"block_number": pl.Int64, "log_index": pl.Int64}, orient="row"
    )
    ell = pl.col("liquidity").cast(pl.Float64)
    fee, lvr = (
        steps.filter(pl.col("accrued") & pl.col("block_number").is_between(p.first, p.last))
        .join(keys, on=["block_number", "log_index"], how="semi")
        .select((pl.col("fee_usd") / ell).sum(), (pl.col("lvr_0") / ell).sum())
        .row(0)
    )
    return {
        "arb_ratio": _ratio(fee, lvr),
        "pool_ratio": _ratio(float(d["fee_kept_pl"].sum()), float(d["lvr_kept_pl"].sum())),
    }


def _verdict_label(rule: str, offset: float) -> str:
    if offset != 0:
        return "sensitivity (+1 s)"
    if rule == OracleFee().name:
        return "upper bound (not tested)"
    if rule.startswith(("vol_", "move_")):
        return "reported in full (not tested)"
    return "baseline"


def _report(
    frozen: dict[str, Any],
    cells: dict[str, StrategyResult],
    runs: FeeRuns,
    real: dict[str, float],
    p: Period,
) -> dict[str, Any]:
    """The report period's range table, fee table and verdicts, all from the frozen values."""
    delta, calibrated = float(frozen["delta"]), bool(frozen["calibration"]["passed"])
    idx = stats.day_index(len(p.days))

    def draws(daily: pl.DataFrame, num: list[str], den: list[str]) -> Any:
        g = stats.on_grid(daily, p.days, [*num, *den])
        return stats.ratio_draws(
            g.select(pl.sum_horizontal(num)).to_series().to_numpy(),
            g.select(pl.sum_horizontal(den)).to_series().to_numpy(),
            idx,
        )

    # Range test (spec 7.1): every cell at $1M paired against full range on the same draws.
    rows = []
    full = range_row(FULL_RANGE, cells[FULL_RANGE])
    base = draws(cells[FULL_RANGE].daily, ["fee_usd"], ["lvr_usd"])
    counted: dict[str, stats.Paired] = {}
    flagged: list[str] = []
    for name, r in cells.items():
        row = range_row(name, r)
        if name != FULL_RANGE:
            pr = stats.paired(
                draws(r.daily, ["fee_usd"], ["lvr_usd"]),
                base,
                row["fees_over_lvr"] - full["fees_over_lvr"],
                delta,
            )
            row |= dict(
                zip(
                    _D_COLUMNS,
                    (pr.point, pr.lo, pr.hi, pr.n_undefined, pr.inside, pr.above),
                    strict=True,
                )
            )
            if row["counted"]:
                counted[name] = pr
                flagged += [name] if row["flagged"] else []
        rows.append(row)
    rows += [range_row(name, r, 0.1) for name, r in cells.items()]
    cols = [
        *STRATEGY_COLUMNS,
        *(f"bp_per_day_taker_{t:g}bp" for t in TAKER_FEE_SENSITIVITY_BP),
        *_D_COLUMNS,
    ]
    ranges = pl.DataFrame([{c: r.get(c) for c in cols} for r in rows], infer_schema_length=None)
    verdict = stats.range_verdict(counted)
    rest = {n: c for n, c in counted.items() if n not in flagged}
    depends = stats.range_verdict(rest) != verdict if rest else bool(flagged)

    # Fee part (spec 7.2): arbitrage side against the 5 bp model run at the same offset.
    five = FixedFee(bp_to_pips(BASELINE_FEE_BP)).name
    ell = float(cells[FULL_RANGE].segs["liquidity"][0])
    twv = float(cells[FULL_RANGE].daily["twv_usd"].sum())
    arb = (["fee_arb_pl"], ["lvr_arb_pl"])

    def sums(daily: pl.DataFrame) -> dict[str, float]:
        cols = [*_PL, "fee_pips_sum", "n_blocks"]
        return {
            c: float(v)
            for c, v in stats.on_grid(daily, p.days, cols)
            .select(cols)
            .sum()
            .row(0, named=True)
            .items()
        }

    level_of = {FixedFee(bp_to_pips(bp)).name: bp for bp in FEE_LEVELS_BP}

    fee_rows: list[dict[str, Any]] = []
    paired_fixed: dict[float, stats.Paired] = {}
    for (rule, off), (daily, _) in runs.items():
        s, b = sums(daily), sums(runs[(five, off)][0])
        pr = stats.paired(
            draws(daily, *arb),
            draws(runs[(five, off)][0], *arb),
            _ratio(s["fee_arb_pl"], s["lvr_arb_pl"]) - _ratio(b["fee_arb_pl"], b["lvr_arb_pl"]),
            delta,
        )
        net, net5 = (
            x["fee_arb_pl"] + x["fee_kept_pl"] - x["lvr_arb_pl"] - x["lvr_kept_pl"] for x in (s, b)
        )
        fee_rows.append(
            {
                "rule": rule,
                "avg_fee_bp": s["fee_pips_sum"] / s["n_blocks"] / 100
                if s["n_blocks"]
                else math.nan,
                "arb_ratio": _ratio(s["fee_arb_pl"], s["lvr_arb_pl"]),
                "d_arb": pr.point,
                "d_arb_lo": pr.lo,
                "d_arb_hi": pr.hi,
                "pool_ratio": _ratio(
                    s["fee_arb_pl"] + s["fee_kept_pl"], s["lvr_arb_pl"] + s["lvr_kept_pl"]
                ),
                "break_even_share": stats.break_even_share(
                    net, net5, s["fee_kept_pl"], s["lvr_kept_pl"]
                ),
                "ref_offset_s": off,
                "verdict": _verdict_label(rule, off),
                "bp_per_day": net * ell / twv * 1e4 if twv > 0 else math.nan,
            }
        )
        if off == 0 and rule in level_of:
            paired_fixed[level_of[rule]] = pr
    per, fee_summary = stats.fee_verdicts(paired_fixed, calibrated)
    level_rows = [r for r in fee_rows if r["ref_offset_s"] == 0 and r["rule"] in level_of]
    for row in level_rows:
        row["verdict"] = per.get(level_of[row["rule"]], row["verdict"])
    levels = [float(level_of[r["rule"]]) for r in level_rows]
    x = stats.break_even_fee(levels, [r["pool_ratio"] for r in level_rows])
    pts = [
        (f, r["break_even_share"])
        for f, r in zip(levels, level_rows, strict=True)
        if r["break_even_share"] is not None
    ]
    y = stats.interp([f for f, _ in pts], [v for _, v in pts], x) if x is not None and pts else None

    fee_rows.append(
        {
            "rule": "real_pool",
            "avg_fee_bp": float(BASELINE_FEE_BP),
            **real,
            "verdict": "reference (real pool)",
            "bp_per_day": full["bp_per_day"],
        }
    )
    d = cells[FULL_RANGE].daily
    fee_usd, lvr_usd = float(d["fee_usd"].sum()), float(d["lvr_usd"].sum())
    for cut in stats.PROTOCOL_CUTS:
        f = stats.protocol_cut(fee_usd, cut)
        fee_rows.append(
            {
                "rule": f"protocol_cut_{cut:g}",
                "avg_fee_bp": float(BASELINE_FEE_BP),
                "pool_ratio": _ratio(f, lvr_usd),
                "verdict": "arithmetic (not tested)",
                "bp_per_day": (f - lvr_usd - full["gas_usd"] - full["trade_usd"]) / twv * 1e4
                if twv > 0
                else math.nan,
            }
        )
    fee_cols = [
        "rule",
        "avg_fee_bp",
        "arb_ratio",
        "d_arb",
        "d_arb_lo",
        "d_arb_hi",
        "pool_ratio",
        "break_even_share",
        "ref_offset_s",
        "verdict",
        "bp_per_day",
    ]
    fees = pl.DataFrame(
        [{c: r.get(c) for c in fee_cols} for r in fee_rows], infer_schema_length=None
    )
    holding = [f for f, v in per.items() if v == "holds"]
    test = {
        "delta": delta,
        "r0": float(frozen["r0"]),
        "range_verdict": verdict,
        "range_verdict_depends_on_flagged_cell": depends,
        "flagged_counted_cells": ", ".join(flagged) or "none",
        "fee_verdict": fee_summary,
        "fee_model_only": not calibrated,
        "lowest_holding_fee_bp": min(holding) if holding else None,
        "break_even_fee_bp_x": x,
        "volume_loss_share_at_x_y": y,
        "fee_level_verdicts": {f"{f:g}bp": v for f, v in per.items()},
        "best_strategy": frozen["best_strategy"]["strategy"],
    }
    return {"ranges": ranges, "fees": fees, "test": test}


def _hedge(
    name: str, r: StrategyResult, starts: pl.DataFrame, extra: StrategyExtras, p: Period
) -> pl.DataFrame:
    """hedge_table for one LP strategy, labelled with it (`rule` keeps the hedge rule)."""
    minutes = extra.perp.filter(pl.col("ts_us").is_between(p.start_us, p.end_us, closed="left"))
    path = position_path(r.segs, starts, minutes)
    t = hedge_table(r.daily, path, extra.perp, extra.funding, PRIMARY_CAPITAL)
    return t.with_columns(rule=pl.col("strategy").str.strip_prefix("hedge_"), strategy=pl.lit(name))


def run_strategy() -> str:
    """Refuses unless validation passed, the latest `ulpe lp` passed its checks and wrote
    summary.json["lp"], and the processed LP files exist."""
    validate.require_validated()
    report.require_passed(config.RESULTS_DIR, "lp_checks", "lp")
    summary = config.RESULTS_DIR / "summary.json"
    if not summary.exists() or "lp" not in json.loads(summary.read_text(encoding="utf-8")):
        raise RuntimeError(f'{summary} has no "lp" results; run `ulpe lp` first')
    raw, interim, proc = config.RAW_DIR, config.INTERIM_DIR, config.PROCESSED_DIR
    lp_files = [proc / f"{n}.parquet" for n in ("swap_steps", "positions", "position_flows")]
    for f in lp_files:
        if not f.exists():
            raise FileNotFoundError(f"{f} missing; run `ulpe lp` first")
    inp = load_lp_inputs(raw, interim, proc, config.LP_LABELS_CSV)
    swap_steps, positions, flows = (read_exact(f) for f in lp_files)
    extra = StrategyExtras(
        positions=positions,
        position_flows=flows,
        swap_steps=swap_steps,
        funding=futures.load_funding(raw),
        perp=futures.load_perp_minutes(raw),
    )
    files = [
        interim / "events.parquet",
        interim / "cex_ethusdc.parquet",
        raw / "tickbook_snapshot.parquet",
        raw / "snapshot_meta.json",
        raw / bq_blocks.BLOCKS_FILE,
        raw / builders.BUILDERS_DIR / builders.TX_OTHER_LOGS,
        *(proc / f"{n}.parquet" for n in ("aligned", "blocks_state", "swap_fees")),
        *lp_files,
        *sorted((raw / futures.FUTURES_DIR).glob("*.zip")),
    ]
    provenance = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": validate.git_commit(),
        "input_hashes": {
            f.relative_to(config.DATA_DIR).as_posix(): validate.file_hash(f) for f in files
        },
    }
    return strategy_analysis(inp, extra, config.RESULTS_DIR, proc, provenance)
