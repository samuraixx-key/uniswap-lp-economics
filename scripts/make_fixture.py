"""Cut a small real-data fixture (first 400 events + nearby snapshot ticks).

The fixture feeds the offline integration test. Before anything is written, the fixture
is replayed here so that a bad band or window fails at generation time, not in the test.
"""

import json
from pathlib import Path

import polars as pl

from uniswap_lp_economics import config
from uniswap_lp_economics.io import read_exact, write_exact
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.validate import replay

N_EVENTS = 400
BAND = 3_000
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def main() -> None:
    meta = json.loads((config.RAW_DIR / "snapshot_meta.json").read_text())
    events = (
        read_exact(config.INTERIM_DIR / "events.parquet")
        .sort("block_number", "log_index")
        .head(N_EVENTS)
    )
    lo, hi = meta["tick"] - BAND, meta["tick"] + BAND
    assert events.filter(pl.col("event") == "swap")["tick"].is_between(lo, hi).all(), (
        "price left the band"
    )
    ticks = read_exact(config.RAW_DIR / "tickbook_snapshot.parquet").filter(
        pl.col("tick").is_between(lo, hi)
    )
    # Self-check: the fixture must replay cleanly on its own, or generation fails here.
    r = replay(
        events,
        TickBook.from_snapshot(ticks, meta),
        int(meta["fee_protocol"]),
        sample_ticks={},
        full_blocks=set(),
    )
    assert r.c1.passed, f"fixture fails C1 replay: {r.c1.mismatches}"
    assert r.c2.passed, f"fixture fails C2 replay: {r.c2.mismatches}"
    OUT.mkdir(parents=True, exist_ok=True)
    write_exact(events, OUT / "fixture_events.parquet")
    write_exact(ticks, OUT / "fixture_ticks.parquet")
    (OUT / "fixture_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"fixture: {events.height} events, {ticks.height} ticks")


if __name__ == "__main__":
    main()
