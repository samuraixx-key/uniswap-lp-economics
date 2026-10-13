"""Parquet I/O for exact-integer columns.

Polars writes ``Int128`` as a private Arrow type that pyarrow, pandas and DuckDB cannot read
(DuckDB silently returns BLOBs). Exact integers are therefore stored on disk as
``Decimal(38, 0)``, which every parquet reader understands, and handled as ``Int128`` in memory.
Use ``write_exact`` / ``read_exact`` for any parquet file that holds Int128 columns.
"""

from pathlib import Path

import polars as pl

DISK_DECIMAL = pl.Decimal(38, 0)


def write_exact(df: pl.DataFrame, path: Path) -> None:
    """Write df with Int128 columns stored as Decimal(38, 0), via a .part file then a rename."""
    int128 = [name for name, dtype in df.schema.items() if dtype == pl.Int128]
    on_disk = df.with_columns(pl.col(int128).cast(DISK_DECIMAL)) if int128 else df
    part = path.with_name(path.name + ".part")
    on_disk.write_parquet(part)
    part.replace(path)


def read_exact(path: Path | list[Path]) -> pl.DataFrame:
    """Read parquet written by write_exact, restoring Decimal(38, 0) columns to Int128."""
    df = pl.read_parquet(path)
    exact = [name for name, dtype in df.schema.items() if dtype == DISK_DECIMAL]
    return df.with_columns(pl.col(exact).cast(pl.Int128)) if exact else df
