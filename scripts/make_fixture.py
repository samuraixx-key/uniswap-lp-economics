"""Cut a small real-data fixture (first 400 events + nearby snapshot ticks).

The fixture feeds the offline integration test.
"""

import json
from pathlib import Path

import polars as pl

from uniswap_lp_economics import config

N_EVENTS = 400
BAND = 3_000
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

meta = json.loads((config.RAW_DIR / "snapshot_meta.json").read_text())
cols = [
    "block_number",
    "log_index",
    "event",
    "tick",
    "sqrt_price_x96",
    "liquidity",
    "tick_lower",
    "tick_upper",
    "amount",
    "fee_protocol0_new",
    "fee_protocol1_new",
]
events = (
    pl.read_parquet(config.INTERIM_DIR / "events.parquet")
    .sort("block_number", "log_index")
    .head(N_EVENTS)
)
events = events.select(cols)
lo, hi = meta["tick"] - BAND, meta["tick"] + BAND
touched = pl.concat([events["tick"], events["tick_lower"], events["tick_upper"]]).drop_nulls()
assert touched.filter(touched.is_between(lo, hi)).len() > 0
assert events.filter(pl.col("event") == "swap")["tick"].is_between(lo, hi).all(), (
    "price left the band"
)
ticks = pl.read_parquet(config.RAW_DIR / "tickbook_snapshot.parquet").filter(
    pl.col("tick").is_between(lo, hi)
)
OUT.mkdir(parents=True, exist_ok=True)
events.write_parquet(OUT / "fixture_events.parquet")
ticks.write_parquet(OUT / "fixture_ticks.parquet")
(OUT / "fixture_meta.json").write_text(json.dumps(meta, indent=2))
print(f"fixture: {events.height} events, {ticks.height} ticks")
