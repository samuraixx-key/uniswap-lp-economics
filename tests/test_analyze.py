import json
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics import analyze as analysis
from uniswap_lp_economics import config, flows
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
        .select("ts_us", "price", qty=pl.lit(1.0), is_buyer_maker=pl.lit(True))
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
    status = analysis.analyze(inp, results, processed, {"git_commit": "test"}, end_us=end_us)
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
    assert len(list((results / "figures").glob("*.png"))) == 6
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    assert summary["swaps"] == inp.swaps.height
    assert summary["git_commit"] == "test"
    assert "upper bound" in summary["limitation"]
    for name in ("arbitrage.md", "bot_profit.md"):
        assert "upper bound" in (results / name).read_text(encoding="utf-8")
    assert (processed / "aligned.parquet").exists()
    assert (processed / "blocks_state.parquet").exists()


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
