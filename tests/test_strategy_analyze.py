"""`ulpe strategy` end to end on the synthetic world: gates, July freeze, report run (spec 4, 9)."""

import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from lpworld import T0, US, WALLET, world_end_us, world_inputs

from uniswap_lp_economics.io import read_exact
from uniswap_lp_economics.lp.analyze import LpInputs, lp_analysis
from uniswap_lp_economics.strategy import analyze
from uniswap_lp_economics.strategy.cfpool import CfRun, prepare_inputs
from uniswap_lp_economics.strategy.checks import replaced_keys
from uniswap_lp_economics.strategy.params import FEE_LEVELS_BP
from uniswap_lp_economics.strategy.ranges import STRATEGY_COLUMNS, LpCosts
from uniswap_lp_economics.validate import CheckResult

SPLIT = int(T0.timestamp()) * US + 86_400 * US  # the world's blocks 6-10 are "July", 11-14 later
HASHES = {"processed/swap_steps.parquet": "0123456789abcdef"}
RESULT_FILES = {
    "strategy_checks.md",
    "strategy_checks.json",  # validate.write_report writes the JSON beside the markdown
    "strategy_ranges.md",
    "strategy_ranges.csv",
    "strategy_fees.md",
    "strategy_fees.csv",
    "strategy_hedge.md",
    "strategy_hedge.csv",
    "strategy_test.md",
    "strategy_freeze.json",
}
FIGURE_FILES = {"strategy_ranges.csv", "strategy_fees.csv", "strategy_hedge.csv"}
World = tuple[LpInputs, analyze.StrategyExtras, Path]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    """The world through `ulpe lp` (for the processed files and summary.json["lp"]), with the
    aligned columns the strategy step reads and an hour of synthetic perp data."""
    inp = world_inputs()
    # the world's aligned price is the pool's own, so it has almost no LVR (r0 >> 1 and delta
    # undefined); a CEX price 30 bp on the trader's side gives every swap LVR above its fee
    p = pl.col("p_cex_0") * pl.when(pl.col("amount_usdc") > 0).then(1.003).otherwise(0.997)
    aligned = inp.aligned.with_columns(p_cex_0=p, p_cex_12=p).with_columns(
        markout_usd_0=-(pl.col("amount_usdc") + pl.col("amount_eth") * pl.col("p_cex_0")),
        sender=pl.lit(WALLET),
        zero_for_one=pl.col("amount_usdc") > 0,
        is_top_bot=pl.lit(True),
        receipt_gas_used=pl.lit(150_000, pl.Int64),
    )
    inp = replace(inp, aligned=aligned)
    base = tmp_path_factory.mktemp("lp")
    results, processed = base / "results", base / "processed"
    results.mkdir()
    (results / "summary.json").write_text(json.dumps({"swaps": 4}))
    status = lp_analysis(inp, results, processed, {"git_commit": "test"}, end_us=world_end_us())
    assert status == "PASS"
    minutes = list(range(SPLIT, SPLIT + 3600 * US, 60 * US))
    extra = analyze.StrategyExtras(
        positions=read_exact(processed / "positions.parquet"),
        position_flows=read_exact(processed / "position_flows.parquet"),
        swap_steps=read_exact(processed / "swap_steps.parquet"),
        funding=pl.DataFrame({"ts_us": [SPLIT + 1800 * US + 2000], "rate": [1e-4]}),
        perp=pl.DataFrame(
            {"ts_us": minutes, "close": [2000.0 + 0.1 * i for i in range(len(minutes))]}
        ),
    )
    return inp, extra, results / "summary.json"


def _run(world: World, tmp_path: Path, hashes: dict[str, str] | None = None) -> str:
    inp, extra, summary = world
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    if not (results / "summary.json").exists():
        shutil.copy(summary, results / "summary.json")
    provenance = {
        "generated_utc": "2026-10-22T00:00:00+00:00",
        "git_commit": "test",
        "input_hashes": HASHES if hashes is None else hashes,
    }
    return analyze.strategy_analysis(
        inp,
        extra,
        results,
        tmp_path / "processed",
        provenance,
        split_us=SPLIT,
        end_us=world_end_us(),
        workers=1,
    )


def _strategy_files(results: Path) -> set[str]:
    files = {p.name for p in results.glob("strategy_*")}
    return files | {f"figure_data/{p.name}" for p in results.glob("figure_data/strategy_*")}


def _record_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every run_pool call's keyword arguments and the last block timestamp it saw."""
    calls: list[dict[str, Any]] = []
    real = analyze.run_pool

    def spy(ci: Any, rule: Any, replace: bool, **kw: Any) -> CfRun:
        calls.append({"replace": replace, "max_ts_us": ci.blocks["ts_us"].max(), **kw})
        return real(ci, rule, replace, **kw)

    monkeypatch.setattr(analyze, "run_pool", spy)
    return calls


def test_first_run_freezes_and_stops(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _record_runs(monkeypatch)
    scored: list[date] = []
    real_score = analyze.score
    monkeypatch.setattr(
        analyze, "score", lambda *a, **kw: scored.extend(a[-1]) or real_score(*a, **kw)
    )
    before = world[2].read_bytes()
    assert _run(world, tmp_path) == "FROZEN"
    results = tmp_path / "results"
    assert _strategy_files(results) == {
        "strategy_freeze.json",
        "strategy_checks.md",
        "strategy_checks.json",
    }
    assert (results / "summary.json").read_bytes() == before
    freeze = json.loads((results / analyze.FREEZE_FILE).read_text(encoding="utf-8"))
    for key in (
        "delta",
        "r0",
        "min_profit_gas",
        "calibration",
        "best_strategy",
        "lp_costs",
        "input_hashes",
    ):
        assert key in freeze, key
    assert set(freeze["lp_costs"]) == {"gas_mint", "gas_burn_collect", "priority_wei"}
    assert freeze["input_hashes"] == HASHES
    assert freeze["min_profit_gas"] == 150_000
    assert freeze["delta"] == pytest.approx((1 - freeze["r0"]) / 4)
    assert freeze["best_strategy"]["rule"] in ("out_of_range", "band", "daily")
    assert set(freeze["cfpool_counts"]) == {"model_0s", "model_1s"}
    assert isinstance(freeze["calibration"]["passed"], bool)
    # S3's measured side stops at the split too: only the replaced swaps before it count
    inp, extra, _ = world
    before = inp.aligned.filter(pl.col("t0_us") < SPLIT).select("block_number", "log_index")
    assert before.height < inp.aligned.height  # the world has swaps past the split
    cal = freeze["calibration"]
    assert cal["replaced_swaps"] == before.height
    measured = extra.swap_steps.join(before, on=["block_number", "log_index"], how="semi")
    assert cal["measured_lvr_usd"] == pytest.approx(float(measured["lvr_0"].sum()))
    checks = (results / "strategy_checks.md").read_text(encoding="utf-8")
    assert "S1 range attribution" in checks and "S3 calibration" in checks
    # no report-period number: the counterfactual runs and the range cells stop at the split
    replaced = [c for c in calls if c["replace"]]
    assert len(replaced) == 2 and all(c["min_profit_gas"] == 150_000 for c in replaced)
    assert all(c["max_ts_us"] < SPLIT for c in replaced)
    assert scored and max(scored) < date(2026, 7, 2)


def test_second_run_writes_every_file(world: World, tmp_path: Path) -> None:
    assert _run(world, tmp_path) == "FROZEN"
    results = tmp_path / "results"
    freeze = (results / analyze.FREEZE_FILE).read_bytes()
    lp_before = json.loads(world[2].read_text(encoding="utf-8"))["lp"]
    assert _run(world, tmp_path) == "PASS"
    assert _strategy_files(results) == RESULT_FILES | {f"figure_data/{n}" for n in FIGURE_FILES}
    assert (results / analyze.FREEZE_FILE).read_bytes() == freeze
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    assert summary["lp"] == lp_before and summary["swaps"] == 4
    s = summary["strategy"]
    assert s["delta"] == json.loads(freeze)["delta"]
    assert s["range_verdict"] in ("holds", "fails", "inconclusive")
    for name in FIGURE_FILES:  # figure data = the results tables' full rows
        assert (results / "figure_data" / name).read_bytes() == (results / name).read_bytes()
    ranges = pl.read_csv(results / "strategy_ranges.csv")
    assert ranges.columns[: len(STRATEGY_COLUMNS)] == list(STRATEGY_COLUMNS)
    assert {"d_ratio", "d_lo", "d_hi"} <= set(ranges.columns)
    assert ranges.height == 2 * 37 and ranges["counted"].sum() == 27
    fees = pl.read_csv(results / "strategy_fees.csv")
    assert {
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
    } <= set(fees.columns)
    assert fees.filter(pl.col("ref_offset_s") == 0).height == 24
    assert fees.filter(pl.col("ref_offset_s") == 1).height == len(FEE_LEVELS_BP)
    assert "real_pool" in fees["rule"].to_list()
    hedge = pl.read_csv(results / "strategy_hedge.csv")
    best = json.loads(freeze)["best_strategy"]["strategy"]
    assert set(hedge["strategy"]) == {"full_range", best}
    assert {"never", "rebalancing_benchmark"} <= set(hedge["rule"])
    for name in ("strategy_ranges.md", "strategy_fees.md", "strategy_hedge.md", "strategy_test.md"):
        assert analyze.COUNTERFACTUAL_NOTE in (results / name).read_text(encoding="utf-8"), name
    assert analyze.FEE_NOTE in (results / "strategy_fees.md").read_text(encoding="utf-8")


def test_failed_gate_writes_only_checks(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        analyze, "check_s1", lambda *a: CheckResult("S1 range attribution vs engine", False, {})
    )
    assert _run(world, tmp_path) == "FAIL"
    assert _strategy_files(tmp_path / "results") == {"strategy_checks.md", "strategy_checks.json"}


def test_freeze_is_write_once(tmp_path: Path) -> None:
    path = tmp_path / analyze.FREEZE_FILE
    with pytest.raises(ValueError):  # strict JSON: a NaN fails before anything is written
        analyze.write_freeze(path, {"delta": float("nan")})
    assert not path.exists()
    analyze.write_freeze(path, {"delta": 0.1})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        analyze.write_freeze(path, {"delta": 0.2})
    assert path.read_bytes() == before


def test_freeze_mismatch_stops(world: World, tmp_path: Path) -> None:
    assert _run(world, tmp_path) == "FROZEN"
    results = tmp_path / "results"
    path = results / analyze.FREEZE_FILE
    before = path.read_bytes()
    with pytest.raises(SystemExit, match="strategy_freeze.json"):
        _run(world, tmp_path, hashes={**HASHES, "raw/blocks.parquet": "ffff"})
    assert path.read_bytes() == before
    with pytest.raises(SystemExit, match="strategy_freeze.json"):
        analyze.read_freeze(path, {"processed/swap_steps.parquet": "other"})
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="strategy_freeze.json"):
        _run(world, tmp_path)
    assert path.read_text(encoding="utf-8") == "{not json"
    inp, extra, _ = world
    with pytest.raises(ValueError, match="input_hashes"):
        analyze.strategy_analysis(inp, extra, results, tmp_path, {"git_commit": "test"})
    assert _strategy_files(results) == {
        "strategy_freeze.json",
        "strategy_checks.md",
        "strategy_checks.json",
    }


def test_frozen_values_win(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(world, tmp_path) == "FROZEN"
    path = tmp_path / "results" / analyze.FREEZE_FILE
    freeze = json.loads(path.read_text(encoding="utf-8"))
    best = "band_100bp"
    assert freeze["best_strategy"]["strategy"] != best
    costs = {"gas_mint": 123_456, "gas_burn_collect": 654_321, "priority_wei": 42}
    edited = {
        **freeze,
        "delta": 0.123456,
        "min_profit_gas": 7,
        "lp_costs": costs,
        "calibration": {**freeze["calibration"], "passed": True},
        "best_strategy": {"strategy": best, "rule": "band", "half_width_bp": 100},
    }
    path.write_text(json.dumps(edited))
    calls = _record_runs(monkeypatch)
    charged: list[LpCosts] = []
    real_score = analyze.score
    monkeypatch.setattr(
        analyze, "score", lambda *a, **kw: charged.append(a[5]) or real_score(*a, **kw)
    )
    assert _run(world, tmp_path) == "PASS"
    replaced = [c for c in calls if c["replace"]]
    assert len(replaced) == 24 + len(FEE_LEVELS_BP)
    assert all(c["min_profit_gas"] == 7 for c in replaced)
    assert len(charged) == 37 and all(c == LpCosts(**costs) for c in charged)
    results = tmp_path / "results"
    test = (results / "strategy_test.md").read_text(encoding="utf-8")
    assert "| delta | 0.1235 |" in test
    # the calibrated path: no model-only label, per-level verdicts tested
    fees_md = (results / "strategy_fees.md").read_text(encoding="utf-8")
    assert analyze.MODEL_ONLY_NOTE not in fees_md and analyze.MODEL_ONLY_NOTE not in test
    verdicts = json.loads((results / "summary.json").read_text(encoding="utf-8"))["strategy"][
        "fee_level_verdicts"
    ]
    for bp in FEE_LEVELS_BP:
        if bp > 5:
            assert verdicts[f"{bp:g}bp"] in ("holds", "fails", "inconclusive"), bp
        elif bp < 5:
            assert verdicts[f"{bp:g}bp"] == "not tested (below baseline)", bp
    hedge = pl.read_csv(results / "strategy_hedge.csv")
    assert set(hedge["strategy"]) == {"full_range", best}


def test_fee_runs_spawns_workers(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    # fork after polars has started its thread pool deadlocks (Linux CI hung 6 h); spawn is safe
    seen: dict[str, Any] = {}

    class Recorder:
        def __init__(self, *args: Any, mp_context: Any = None, **kwargs: Any) -> None:
            seen["start"] = mp_context.get_start_method() if mp_context else None

        def __enter__(self) -> "Recorder":
            raise RuntimeError("stop")

        def __exit__(self, *exc: Any) -> None:
            pass

    monkeypatch.setattr(analyze, "ProcessPoolExecutor", Recorder)
    with pytest.raises(RuntimeError, match="stop"):
        analyze.fee_runs(world[0], 0, workers=2)  # type: ignore[arg-type]
    assert seen["start"] == "spawn"


def test_fee_runs_in_worker_processes_match_in_process(world: World) -> None:
    inp = world[0]
    ci = prepare_inputs(
        inp.events,
        inp.ticks,
        inp.meta,
        inp.aligned,
        inp.swap_fees,
        inp.blocks_state,
        inp.blocks,
        inp.trades,
        replaced_keys(inp.aligned, inp.tx_other_logs),
        world_end_us(),
    )
    one = analyze.fee_runs(ci, 0, workers=1)
    two = analyze.fee_runs(ci, 0, workers=2)
    assert one.keys() == two.keys() and len(one) == 24 + len(FEE_LEVELS_BP)
    for k, (daily, counts) in one.items():
        assert daily.equals(two[k][0]) and counts == two[k][1], k


def test_run_strategy_refuses_after_a_failed_lp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(analyze.validate, "require_validated", lambda: None)
    monkeypatch.setattr(analyze.config, "RESULTS_DIR", tmp_path)
    (tmp_path / "summary.json").write_text('{"lp": {}}', encoding="utf-8")
    (tmp_path / "lp_checks.json").write_text('{"status": "FAIL"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="lp_checks.json status is FAIL"):
        analyze.run_strategy()
