"""Offline replay of real mainnet events: runs in CI without keys or network."""

import json
from pathlib import Path

import polars as pl

from uniswap_lp_economics.io import read_exact
from uniswap_lp_economics.replay import iter_block_starts
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.validate import replay

FIX = Path(__file__).parent / "fixtures"


def _fixture() -> tuple[dict[str, int], TickBook, pl.DataFrame]:
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    book = TickBook.from_snapshot(read_exact(FIX / "fixture_ticks.parquet"), meta)
    return meta, book, read_exact(FIX / "fixture_events.parquet")


def test_real_events_replay_cleanly() -> None:
    meta, book, events = _fixture()
    r = replay(events, book, int(meta["fee_protocol"]), sample_ticks={}, full_blocks=set())
    assert r.c1.summary["swaps"] > 0
    assert r.c1.passed, r.c1.mismatches
    assert r.c2.passed, r.c2.mismatches


def test_block_starts_end_at_last_swap_price() -> None:
    meta, book, events = _fixture()
    first = int(meta["block"]) + 1
    last = int(events["block_number"].max())  # type: ignore[arg-type]
    seen = list(iter_block_starts(events, book, int(meta["fee_protocol"]), first, last))
    assert seen == list(range(first, last + 2))
    last_swap = events.filter(pl.col("event") == "swap").sort("block_number", "log_index").tail(1)
    assert book.sqrt_price_x96 == last_swap["sqrt_price_x96"].item()
