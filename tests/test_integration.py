"""Offline replay of real mainnet events: runs in CI without keys or network."""

import json
from pathlib import Path

from uniswap_lp_economics.io import read_exact
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.validate import replay

FIX = Path(__file__).parent / "fixtures"


def test_real_events_replay_cleanly() -> None:
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    book = TickBook.from_snapshot(read_exact(FIX / "fixture_ticks.parquet"), meta)
    events = read_exact(FIX / "fixture_events.parquet")
    r = replay(events, book, int(meta["fee_protocol"]), sample_ticks={}, full_blocks=set())
    assert r.c1.summary["swaps"] > 0
    assert r.c1.passed, r.c1.mismatches
    assert r.c2.passed, r.c2.mismatches
