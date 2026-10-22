"""Flow labels for swaps: a curated address list first, then structural heuristics (spec 5.4)."""

import re
from pathlib import Path

import polars as pl

from uniswap_lp_economics.io import ordered_group_by

CATEGORIES = ("uniswap_router", "aggregator", "intent_settlement")
FLOW_LABELS = (*CATEGORIES, "searcher", "other_contract")
LABEL_COLUMNS = ["address", "name", "category", "source_url", "notes"]
SIZE_BUCKETS = ("<1k", "1k-10k", "10k-100k", ">=100k")
TOP_OF_BLOCK_MAX_INDEX = 2
TOP_BOT_COVERAGE = 0.9
TOP_BOT_CAP = 25
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


def load_labels(path: Path) -> pl.DataFrame:
    """Read and validate the curated address list; a ValueError names the offending line."""
    df = pl.read_csv(path, infer_schema=False)
    if df.columns != LABEL_COLUMNS:
        raise ValueError(f"{path}: columns must be {LABEL_COLUMNS}, got {df.columns}")
    for line, row in enumerate(df.iter_rows(named=True), start=2):  # line 1 is the header
        if not _ADDRESS.match(row["address"] or ""):
            raise ValueError(
                f"{path} line {line}: address {row['address']!r} must be 0x + 40 lowercase hex"
            )
        if row["category"] not in CATEGORIES:
            raise ValueError(
                f"{path} line {line}: category {row['category']!r} not in {CATEGORIES}"
            )
        if not row["name"]:
            raise ValueError(f"{path} line {line}: name is empty")
        if not (row["source_url"] or "").startswith("https://"):
            raise ValueError(f"{path} line {line}: source_url must be an https:// link")
    dupes = sorted(set(df.filter(pl.col("address").is_duplicated())["address"].to_list()))
    if dupes:
        raise ValueError(f"{path}: duplicate addresses {dupes}")
    return df


def size_bucket(notional: pl.Expr) -> pl.Expr:
    return (
        pl.when(notional < 1_000)
        .then(pl.lit(SIZE_BUCKETS[0]))
        .when(notional < 10_000)
        .then(pl.lit(SIZE_BUCKETS[1]))
        .when(notional < 100_000)
        .then(pl.lit(SIZE_BUCKETS[2]))
        .otherwise(pl.lit(SIZE_BUCKETS[3]))
    )


def label_swaps(swaps: pl.DataFrame, labels: pl.DataFrame) -> pl.DataFrame:
    """Add flow_label, top_of_block and size_bucket. First matching rule wins: tx target listed →
    its category; pool caller listed → its category; caller == tx target → searcher; else
    other_contract."""
    cats = labels.select("address", "category")
    joined = swaps.join(
        cats.rename({"address": "to_address", "category": "_cat_to"}),
        on="to_address",
        how="left",
        maintain_order="left",
    ).join(
        cats.rename({"address": "sender", "category": "_cat_sender"}),
        on="sender",
        how="left",
        maintain_order="left",
    )
    searcher = pl.when(pl.col("sender") == pl.col("to_address")).then(pl.lit("searcher"))
    return joined.with_columns(
        flow_label=pl.coalesce("_cat_to", "_cat_sender", searcher, pl.lit("other_contract")),
        top_of_block=pl.col("transaction_index") <= TOP_OF_BLOCK_MAX_INDEX,
        size_bucket=size_bucket(pl.col("notional_usd")),
    ).drop("_cat_to", "_cat_sender")


def top_bots(
    labelled: pl.DataFrame, coverage: float = TOP_BOT_COVERAGE, cap: int = TOP_BOT_CAP
) -> list[str]:
    """Smallest set of searcher senders, ranked by notional, covering `coverage` (at most `cap`)."""
    ranked = (
        labelled.filter(pl.col("flow_label") == "searcher")
        .group_by("sender")
        .agg(pl.col("notional_usd").sum())
        .sort(["notional_usd", "sender"], descending=[True, False])
    )
    total = float(ranked["notional_usd"].sum())
    bots: list[str] = []
    covered = 0.0
    for sender, notional in ranked.iter_rows():
        if total <= 0 or covered >= coverage * total or len(bots) == cap:
            break
        bots.append(sender)
        covered += notional
    return bots


def label_coverage(labelled: pl.DataFrame) -> pl.DataFrame:
    total = float(labelled["notional_usd"].sum())
    share = pl.col("notional_usd") / total if total > 0 else pl.lit(None, dtype=pl.Float64)
    return (
        ordered_group_by(labelled, "flow_label")
        .agg(swaps=pl.len(), notional_usd=pl.col("notional_usd").sum())
        .with_columns(notional_share=share)
        .sort("notional_usd", descending=True)
    )


def top_unlabelled(labelled: pl.DataFrame, column: str, n: int = 30) -> pl.DataFrame:
    """The `column` values (sender or to_address) of other_contract swaps with most notional."""
    return (
        labelled.filter(pl.col("flow_label") == "other_contract")
        .group_by(pl.col(column).alias("address"))
        .agg(swaps=pl.len(), notional_usd=pl.col("notional_usd").sum())
        .sort(["notional_usd", "address"], descending=[True, False])
        .head(n)
    )
