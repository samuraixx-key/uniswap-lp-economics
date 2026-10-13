"""Offline replay of real mainnet events: runs in CI without keys or network."""

import json
from pathlib import Path

import polars as pl

from uniswap_lp_economics.io import read_exact
from uniswap_lp_economics.replay import iter_block_starts, iter_swaps_with_pre_state, required
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3swap import check_swap_event, swap_check_ok
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


def test_v3swap_reproduces_fixture_swaps() -> None:
    meta, book, events = _fixture()
    checked = exact = 0
    for row in iter_swaps_with_pre_state(events, book, int(meta["fee_protocol"])):
        c = check_swap_event(
            book,
            required(row, "amount0"),
            required(row, "amount1"),
            required(row, "sqrt_price_x96"),
        )
        if c is None:
            continue
        checked += 1
        exact += c.exact
        assert swap_check_ok(c), (row.block_number, row.log_index, c)
    assert checked > 300
    assert exact > 300
