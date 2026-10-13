"""ONE-OFF migration: rewrite raw parquet files from Polars' private Int128 to Decimal(38, 0).

Before ruling R17 the fetch steps wrote exact-integer columns as Polars ``Int128``, which pyarrow,
pandas and DuckDB cannot read. Files fetched afterwards are already written correctly (see
``uniswap_lp_economics.io``); this script converts the three files that were fetched earlier, in
place and without any network or RPC call:

    data/raw/tickbook_snapshot.parquet
    data/raw/onchain_samples.parquet
    data/raw/onchain_sample_ticks.parquet

Each file is read as Int128, written to ``<name>.migrated``, re-read and checked for exact equality,
and only then renamed over the original. Files that hold no Int128 column are left alone, so
re-running is harmless. ``pool_logs_*.parquet`` hold no Int128 columns and are not touched.
Delete this script once every checkout has been migrated.

Usage: uv run python scripts/migrate_int128_to_decimal.py
"""

import polars as pl

from uniswap_lp_economics import config
from uniswap_lp_economics.io import read_exact, write_exact

FILES = ["tickbook_snapshot.parquet", "onchain_samples.parquet", "onchain_sample_ticks.parquet"]


def main() -> None:
    for name in FILES:
        path = config.RAW_DIR / name
        if not path.exists():
            print(f"{name}: not present, skipped")
            continue
        old = pl.read_parquet(path)  # Int128 columns come back as Int128
        int128 = [c for c, t in old.schema.items() if t == pl.Int128]
        if not int128:
            print(f"{name}: no Int128 columns, already migrated")
            continue
        tmp = path.with_name(path.name + ".migrated")
        write_exact(old, tmp)
        if not read_exact(tmp).equals(old):
            tmp.unlink()
            raise RuntimeError(f"{name}: migrated copy differs from the original; nothing changed")
        tmp.replace(path)
        print(f"{name}: {old.height:,} rows, Int128 -> Decimal(38, 0) in {int128}")


if __name__ == "__main__":
    main()
