from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pyarrow.parquet as pq
import pytest

from uniswap_lp_economics.io import (
    hex_u256,
    ordered_group_by,
    read_exact,
    u256_hex,
    write_exact,
    write_text_atomic,
)

BIG = 2**120 + 12_345
MAX38 = 10**38 - 1  # largest value Decimal(38, 0) holds
VALUES = [0, 1, -1, BIG, -BIG, MAX38, -MAX38]


def frame() -> pl.DataFrame:
    return pl.DataFrame(
        {"id": list(range(len(VALUES))), "x": VALUES, "f": [0.5] * len(VALUES)},
        schema={"id": pl.Int64, "x": pl.Int128, "f": pl.Float64},
    )


def test_polars_round_trip_is_exact_int128(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    write_exact(frame(), path)
    back = read_exact(path)
    assert back.schema == frame().schema
    assert back["x"].to_list() == VALUES
    assert not (tmp_path / "t.parquet.part").exists()


def test_on_disk_type_is_decimal_not_private_int128(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    write_exact(frame(), path)
    assert pl.read_parquet(path).schema["x"] == pl.Decimal(38, 0)
    schema = pq.read_schema(path)  # raises on Polars' private Int128 encoding
    assert str(schema.field("x").type) == "decimal128(38, 0)"
    assert pq.read_table(path).column("x").to_pylist()[3] == BIG


def test_duckdb_reads_exact_decimal(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    write_exact(frame(), path)
    rel = duckdb.sql(f"select x from read_parquet('{path.as_posix()}') where id = 3")
    assert rel.types[0].id == "decimal"
    assert rel.fetchall()[0][0] == BIG
    total = duckdb.sql(f"select sum(x) from read_parquet('{path.as_posix()}')").fetchall()[0][0]
    assert total == sum(VALUES)


def test_frame_without_int128_is_untouched(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    df = pl.DataFrame({"a": [1, 2], "s": ["x", "y"]})
    write_exact(df, path)
    assert read_exact(path).equals(df)


def test_value_beyond_38_digits_fails_loudly(tmp_path: Path) -> None:
    df = pl.DataFrame({"x": [10**38]}, schema={"x": pl.Int128})
    with pytest.raises(pl.exceptions.PolarsError):
        write_exact(df, tmp_path / "t.parquet")
    assert list(tmp_path.iterdir()) == []


def test_write_text_atomic_replaces_and_leaves_no_part(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text("old")
    write_text_atomic(path, "new")
    assert path.read_text() == "new"
    assert list(tmp_path.iterdir()) == [path]


def test_write_text_atomic_writes_utf8_with_lf_newlines(tmp_path: Path) -> None:
    path = tmp_path / "m.md"
    text = "→ ≥ μ é\nsecond line\n"  # arrow, >=, mu, e-acute
    write_text_atomic(path, text)
    assert path.read_bytes() == text.encode("utf-8")
    assert b"\r" not in path.read_bytes()
    assert list(tmp_path.iterdir()) == [path]


def test_u256_hex_round_trip_and_wrap() -> None:
    assert u256_hex(255) == "0" * 62 + "ff"
    assert len(u256_hex(2**256 - 1)) == 64
    assert u256_hex(-1) == "f" * 64  # wraps like uint256
    assert hex_u256(u256_hex(2**200 + 7)) == 2**200 + 7


def test_ordered_group_by_is_deterministic() -> None:
    # guards a polars behaviour, not a promise: plain group_by sums differ on nearly every call
    rng = np.random.default_rng(0)
    n = 1_000_000
    df = pl.DataFrame(
        {"day": rng.integers(0, 61, n), "x": rng.standard_normal(n) * rng.lognormal(0, 3, n)}
    )
    runs = {
        ordered_group_by(df, "day").agg(pl.col("x").sum(), m=pl.col("x").mean()).write_csv()
        for _ in range(20)
    }
    assert len(runs) == 1
    out = ordered_group_by(df, "day").agg(pl.col("x").sum())
    assert out["day"].to_list() == list(range(61))  # groups in key order
