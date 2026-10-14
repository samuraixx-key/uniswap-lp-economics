import json
import math
from datetime import date
from pathlib import Path

import polars as pl

from uniswap_lp_economics.report import (
    LIMITATION_TEXT,
    markdown_table,
    metrics_table,
    write_summary,
    write_table,
)


def test_markdown_table_formats_values() -> None:
    df = pl.DataFrame({"name": ["a", None], "n": [1234567, 2], "x": [1.23456, math.nan]})
    assert markdown_table(df).splitlines() == [
        "| name | n | x |",
        "|---|---|---|",
        "| a | 1,234,567 | 1.23 |",
        "|  | 2 |  |",
    ]
    assert markdown_table(df.head(0)).splitlines() == ["| name | n | x |", "|---|---|---|"]


def test_metrics_table_flattens_nested_dicts() -> None:
    t = metrics_table({"blocks": 3, "quantiles_bp": {"0.5": 1.5}})
    assert t.rows() == [("blocks", "3"), ("quantiles_bp.0.5", "1.5000")]


def test_write_table_writes_csv_and_markdown_with_notes(tmp_path: Path) -> None:
    write_table(pl.DataFrame({"a": [1]}), tmp_path, "t", "Title", notes=[LIMITATION_TEXT])
    assert (tmp_path / "t.csv").read_text().splitlines() == ["a", "1"]
    md = (tmp_path / "t.md").read_text()
    assert md.startswith("# Title") and "upper bound" in md and "| a |" in md


def test_write_summary_cleans_values(tmp_path: Path) -> None:
    write_summary({"x": math.inf, "y": [math.nan, 1.0], "d": date(2026, 7, 1)}, tmp_path)
    assert json.loads((tmp_path / "summary.json").read_text()) == {
        "x": None,
        "y": [None, 1.0],
        "d": "2026-07-01",
    }
