"""Everything the figures read, from results/ only (chart redesign spec sections 2 and 4)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.lp.figdata import JIT_BLOCK_SCHEMA

# results file -> the `ulpe` command that writes it
SOURCES = {
    "summary.json": "analyze",
    "markouts.csv": "analyze",
    "bot_profit.csv": "analyze",
    "episodes.csv": "analyze",
    "figure_data/basis_hist.csv": "analyze",
    "lvr_daily.csv": "lp",
    "positions.csv": "lp",
    "lp_groups.csv": "lp",
    "figure_data/episode_blocks.csv": "lp",
    "figure_data/episode_cex.csv": "lp",
    "figure_data/jit_block.csv": "lp",
}
SUMMARY_KEYS = {"lead_lag": "analyze", "arbitrage": "analyze", "lp": "lp"}
# Column types the figures rely on, so a table with only a header still reads with them.
TYPES: dict[str, dict[str, Any]] = {
    "episodes.csv": {"duration_s": pl.Float64, "threshold_bp": pl.Float64},
    "bot_profit.csv": {"sender": pl.String, "gross_usd": pl.Float64, "kept_usd": pl.Float64},
    "figure_data/basis_hist.csv": {
        "bin_lo_bp": pl.Float64,
        "bin_hi_bp": pl.Float64,
        "blocks": pl.Int64,
    },
    "figure_data/episode_blocks.csv": {
        "block_number": pl.Int64,
        "ts_us": pl.Int64,
        "pool_price": pl.Float64,
        "p_cex": pl.Float64,
        "lvr_0_usd": pl.Float64,
        "has_searcher": pl.Boolean,
    },
    "figure_data/episode_cex.csv": {"ts_us": pl.Int64, "price": pl.Float64},
    "figure_data/jit_block.csv": JIT_BLOCK_SCHEMA,
}
LP_KEYS = (
    "destination",
    "daily",
    "lifetime",
    "lifetime_by_life",
    "lifetime_by_width",
    "fees_minus_lvr_usd",
)


def window_label(daily: pl.DataFrame) -> str:
    """The window as months, from the daily series: "Jul–Sep 2026", "Jul 2026"."""
    days = daily["day"].to_list()
    first, last = min(days), max(days)
    if (first.year, first.month) == (last.year, last.month):
        return f"{first:%b %Y}"
    if first.year == last.year:
        return f"{first:%b}–{last:%b %Y}"
    return f"{first:%b %Y}–{last:%b %Y}"


@dataclass(frozen=True)
class Results:
    summary: dict[str, Any]
    markouts: pl.DataFrame
    bot_profit: pl.DataFrame
    episodes: pl.DataFrame
    basis_hist: pl.DataFrame
    daily: pl.DataFrame
    positions: pl.DataFrame
    groups: pl.DataFrame
    episode_blocks: pl.DataFrame
    episode_cex: pl.DataFrame
    jit_block: pl.DataFrame


def load_results(d: Path) -> Results:
    missing = [
        f"{d / f} missing; run `ulpe {cmd}`" for f, cmd in SOURCES.items() if not (d / f).exists()
    ]
    if missing:
        raise FileNotFoundError("; ".join(missing))
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    gaps = [
        f"summary.json has no {k!r}; run `ulpe {cmd}`"
        for k, cmd in SUMMARY_KEYS.items()
        if k not in summary
    ]
    gaps += [
        f"summary.json has no lp.{k}; run `ulpe lp`"
        for k in LP_KEYS
        if "lp" in summary and k not in summary["lp"]
    ]
    if gaps:
        raise FileNotFoundError("; ".join(gaps))

    def csv(name: str) -> pl.DataFrame:
        return pl.read_csv(d / name, try_parse_dates=True, schema_overrides=TYPES.get(name))

    return Results(
        summary=summary,
        markouts=csv("markouts.csv"),
        bot_profit=csv("bot_profit.csv"),
        episodes=csv("episodes.csv"),
        basis_hist=csv("figure_data/basis_hist.csv"),
        daily=csv("lvr_daily.csv"),
        positions=csv("positions.csv"),
        groups=csv("lp_groups.csv"),
        episode_blocks=csv("figure_data/episode_blocks.csv"),
        episode_cex=csv("figure_data/episode_cex.csv"),
        jit_block=csv("figure_data/jit_block.csv"),
    )
