import json
import sys
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics import analyze as analysis
from uniswap_lp_economics import cli, config, flows
from uniswap_lp_economics.build import build_swaps
from uniswap_lp_economics.data.transfers import TRANSFER_SCHEMA
from uniswap_lp_economics.io import read_exact, write_exact

FIX = Path(__file__).parent / "fixtures"
MINER = "0x" + "ee" * 20
US = 1_000_000


def fixture_inputs() -> tuple[analysis.Inputs, int]:
    """The real 400-event fixture plus synthetic blocks, Binance prices and bot data."""
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    events = read_exact(FIX / "fixture_events.parquet")
    swaps = build_swaps(events, int(meta["sqrt_price_x96"]), int(meta["fee_protocol"]))
    labels = flows.load_labels(config.LABELS_CSV)
    bots = flows.top_bots(flows.label_swaps(swaps, labels))

    first = int(meta["block"]) + 1
    last = int(events["block_number"].max())  # type: ignore[arg-type]
    stamps = events.group_by("block_number").agg(pl.col("block_timestamp").first())
    blocks = (
        pl.DataFrame(
            {"block_number": list(range(first, last + 1))}, schema={"block_number": pl.Int64}
        )
        .join(stamps, on="block_number", how="left", maintain_order="left")
        .with_columns(
            pl.col("block_timestamp").fill_null(strategy="forward"),
            miner=pl.lit(MINER),
            base_fee_per_gas=pl.lit(10**9, dtype=pl.Int64),
        )
    )

    ts = events["block_timestamp"].dt.epoch("us")
    t_first, t_last = int(ts.min()), int(ts.max())  # type: ignore[arg-type]
    seconds = pl.DataFrame({"ts_us": list(range(t_first - 60 * US, t_last + 3700 * US, US))})
    pool = swaps.select(ts_us=pl.col("block_timestamp").dt.epoch("us"), px=pl.col("price_usd"))
    trades = (
        seconds.join_asof(pool.sort("ts_us"), on="ts_us", strategy="backward")
        .with_columns(price=pl.col("px").fill_null(strategy="backward") * 1.0003)
        .with_row_index("agg_trade_id")
        .select(
            pl.col("agg_trade_id").cast(pl.Int64),
            "ts_us",
            "price",
            qty=pl.lit(1.0),
            is_buyer_maker=pl.lit(True),
        )
    )
    klines = trades.select("ts_us", close="price")

    bot_txs = swaps.filter(pl.col("to_address").is_in(bots))["tx_hash"].unique().sort().to_list()
    assert len(bot_txs) >= 2
    other_logs = pl.DataFrame(
        {"tx_hash": bot_txs, "other_logs": [3] + [0] * (len(bot_txs) - 1)},
        schema={"tx_hash": pl.String, "other_logs": pl.Int64},
    )
    paid = swaps.filter(pl.col("tx_hash") == bot_txs[1]).row(0, named=True)
    transfers = pl.DataFrame(
        [(paid["block_number"], paid["tx_hash"], paid["to_address"], MINER, 10**15)],
        schema=TRANSFER_SCHEMA,
        orient="row",
    )
    inp = analysis.Inputs(
        events=events,
        swaps=swaps,
        trades=trades,
        klines=klines,
        ticks=read_exact(FIX / "fixture_ticks.parquet"),
        meta=meta,
        blocks=blocks,
        other_logs=other_logs,
        transfers=transfers,
        labels=labels,
        bots=bots,
    )
    return inp, t_last + 3700 * US


def test_analyze_fixture_end_to_end(tmp_path: Path) -> None:
    inp, end_us = fixture_inputs()
    results, processed = tmp_path / "results", tmp_path / "processed"
    status = analysis.analyze(
        inp,
        results,
        processed,
        {"git_commit": "test"},
        end_us=end_us,
        blocks_end_us=int(inp.blocks["block_timestamp"].dt.epoch("us").max()) + 1,
    )
    assert status == "PASS", (results / "analysis_checks.md").read_text(encoding="utf-8")
    for name in (
        "summary.json",
        "markouts.csv",
        "markouts.md",
        "markouts_robustness.csv",
        "markouts_robustness.md",
        "labels_coverage.md",
        "basis.md",
        "episodes.csv",
        "episodes.md",
        "leadlag.md",
        "arbitrage.md",
        "bot_profit.csv",
        "bot_profit.md",
    ):
        assert (results / name).exists(), name
    assert not (results / "figures").exists()  # `ulpe figures` draws; analyze writes data only
    hist = pl.read_csv(results / "figure_data" / "basis_hist.csv")
    assert hist.columns == ["bin_lo_bp", "bin_hi_bp", "blocks"] and hist.height == 200
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    assert summary["swaps"] == inp.swaps.height
    assert summary["git_commit"] == "test"
    assert "upper bound" in summary["limitation"]
    keys_12s = ("top_bot_single_pool_gross_12s_usd", "kept_12s_usd", "kept_over_top_bot_gross_12s")
    assert set(keys_12s) <= summary["arbitrage"].keys()
    assert all(k in (results / "arbitrage.md").read_text(encoding="utf-8") for k in keys_12s)
    for name in ("arbitrage.md", "bot_profit.md"):
        assert "upper bound" in (results / name).read_text(encoding="utf-8")
    assert (processed / "aligned.parquet").exists()
    assert (processed / "blocks_state.parquet").exists()
    assert (processed / "swap_fees.parquet").exists()
    assert summary["markouts_robustness_0s"]
    assert {r["horizon_s"] for r in summary["markouts_robustness_0s"]} == {0}
    assert all(r["grouping"] == "flow_label_x_size" for r in summary["markouts_by_label_x_size_0s"])


def test_failed_gated_check_writes_no_results(tmp_path: Path) -> None:
    inp, end_us = fixture_inputs()
    # A hole in the Binance data: trades after the first hour carry no price, so swaps there get
    # a null reference inside the data range and A4 fails. (Truncating the trades would not do:
    # the as-of lookup would then return the last, stale price instead of a null.)
    cutoff = int(inp.trades["ts_us"].min()) + 3600 * US  # type: ignore[arg-type]
    inp.trades = inp.trades.with_columns(
        price=pl.when(pl.col("ts_us") < cutoff).then(pl.col("price"))
    )
    results, processed = tmp_path / "results", tmp_path / "processed"
    status = analysis.analyze(
        inp,
        results,
        processed,
        {"git_commit": "test"},
        end_us=end_us,
        blocks_end_us=int(inp.blocks["block_timestamp"].dt.epoch("us").max()) + 1,
    )
    assert status == "FAIL"
    checks_md = (results / "analysis_checks.md").read_text(encoding="utf-8")
    assert "| A4 Binance reference coverage | FAIL |" in checks_md
    assert not (results / "summary.json").exists()
    assert not (results / "markouts.csv").exists()
    assert not (results / "figures").exists()
    assert not (processed / "aligned.parquet").exists()
    assert not (processed / "blocks_state.parquet").exists()


def test_load_inputs_names_the_missing_fetch(tmp_path: Path) -> None:
    raw, interim = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    interim.mkdir()
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    events = read_exact(FIX / "fixture_events.parquet")
    swaps = build_swaps(events, int(meta["sqrt_price_x96"]), int(meta["fee_protocol"]))
    write_exact(swaps, interim / "swaps.parquet")
    with pytest.raises(FileNotFoundError, match="ulpe fetch-blocks"):
        analysis.load_inputs(raw, interim, config.LABELS_CSV)


def test_cli_analyze_turns_value_error_into_clean_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_labels() -> str:
        raise ValueError("labels/addresses.csv: bad address in row 3")

    monkeypatch.setattr(analysis, "run_analysis", bad_labels)
    monkeypatch.setattr(sys, "argv", ["ulpe", "analyze"])
    with pytest.raises(SystemExit, match="bad address in row 3"):
        cli.main()


def _own(**extra: Any) -> dict[str, Any]:
    return {"generated_utc": "t1", "git_commit": "c1", "swaps": 3, "basis": {"x": 1.5}, **extra}


def test_carry_downstream_keeps_lp_and_strategy_when_own_output_unchanged(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({**_own(), "lp": {"a": 1}, "strategy": {"b": 2}}), encoding="utf-8")
    new = {**_own(), "generated_utc": "t2", "git_commit": "c2"}
    out = analysis.carry_downstream(new, p)
    assert out["lp"] == {"a": 1} and out["strategy"] == {"b": 2}
    assert out["generated_utc"] == "t2" and out["git_commit"] == "c2"


def test_carry_downstream_drops_them_when_own_output_changed(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    p.write_text(json.dumps({**_own(), "lp": {"a": 1}, "strategy": {"b": 2}}), encoding="utf-8")
    out = analysis.carry_downstream({**_own(), "swaps": 4}, p)
    assert "lp" not in out and "strategy" not in out


def test_carry_downstream_compares_as_written(tmp_path: Path) -> None:
    # NaN is written as null and tuples as lists: an unchanged run must still carry the keys
    p = tmp_path / "summary.json"
    old = {**_own(), "v": None, "t": [1, 2], "lp": {"a": 1}}
    p.write_text(json.dumps(old), encoding="utf-8")
    out = analysis.carry_downstream({**_own(), "v": float("nan"), "t": (1, 2)}, p)
    assert out["lp"] == {"a": 1}


def test_carry_downstream_without_a_readable_file_adds_nothing(tmp_path: Path) -> None:
    p = tmp_path / "summary.json"
    assert analysis.carry_downstream(_own(), p) == _own()
    p.write_text("{not json", encoding="utf-8")
    assert analysis.carry_downstream(_own(), p) == _own()
