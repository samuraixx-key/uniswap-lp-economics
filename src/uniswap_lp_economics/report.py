"""Tables and the summary for results/: CSV + markdown pairs, and summary.json."""

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.io import write_text_atomic

LIMITATION_TEXT = (
    "Builder payments are detected only as direct ETH transfers from the bot contract to the "
    "block's fee recipient within the same transaction. Payments routed elsewhere (another "
    "contract, a separate transaction in the bundle, off-chain agreements) are missed, so the "
    "reported net profit is an **upper bound** on what the bots keep. Binance-side trading fees, "
    "inventory and hedging costs are not observed."
)


def _fmt(value: object, digits: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return "" if math.isnan(value) else f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def markdown_table(df: pl.DataFrame, digits: int = 2) -> str:
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(_fmt(v, digits) for v in row) + " |" for row in df.iter_rows()]
    return "\n".join(lines) + "\n"


def metrics_table(metrics: dict[str, Any]) -> pl.DataFrame:
    """Flatten a nested dict into (metric, value) rows; nested keys are joined with dots."""
    rows: list[tuple[str, str]] = []

    def walk(prefix: str, obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        else:
            rows.append((prefix, _fmt(obj, 4)))

    walk("", metrics)
    return pl.DataFrame(rows, schema={"metric": pl.String, "value": pl.String}, orient="row")


def write_markdown(
    out_dir: Path,
    stem: str,
    title: str,
    sections: list[tuple[str, pl.DataFrame]],
    notes: list[str] | None = None,
    digits: int = 2,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = [f"# {title}", ""]
    for note in notes or []:
        parts += [note, ""]
    for heading, df in sections:
        if heading:
            parts += [f"## {heading}", ""]
        parts += [markdown_table(df, digits)]
    write_text_atomic(out_dir / f"{stem}.md", "\n".join(parts))


def write_table(
    df: pl.DataFrame,
    out_dir: Path,
    stem: str,
    title: str,
    notes: list[str] | None = None,
    digits: int = 2,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(out_dir / f"{stem}.csv", df.write_csv())
    write_markdown(out_dir, stem, title, [("", df)], notes, digits)


def clean(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [clean(v) for v in obj]
    if isinstance(obj, date):  # datetime is a date too
        return obj.isoformat()
    return obj


def write_summary(summary: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(out_dir / "summary.json", json.dumps(clean(summary), indent=2) + "\n")
