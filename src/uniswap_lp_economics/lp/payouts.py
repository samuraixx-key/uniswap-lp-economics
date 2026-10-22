"""Who pays the proposer (spec section 4): every window block gets one of five classes from chain
data only. The relay is not used here; it checks the classes on a holdout later."""

import polars as pl

EMPTY, PAID, PAYOUT = "empty", "paid", "payout"
PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED = "proposer_is_fee_recipient", "unexplained"
CLASSES = (EMPTY, PAID, PAYOUT, PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED)
PAYOUT_MIN_BLOCKS = 50
PAYOUT_MIN_POSITIVE_SHARE = 0.99


def payout_pairs(block_revenue: pl.DataFrame) -> pl.DataFrame:
    """(miner, last_from) where a sender other than the fee recipient sent the block's last
    transaction in at least PAYOUT_MIN_BLOCKS of the miner's blocks, with value > 0 in at least
    PAYOUT_MIN_POSITIVE_SHARE of them. Learned from block_revenue only."""
    return (
        block_revenue.filter(pl.col("last_from").is_not_null())
        .filter(pl.col("last_from") != pl.col("miner"))
        .group_by("miner", "last_from")
        .agg(n=pl.len(), positive=(pl.col("last_value_wei") > 0).sum())
        .filter(
            (pl.col("n") >= PAYOUT_MIN_BLOCKS)
            & (pl.col("positive") >= PAYOUT_MIN_POSITIVE_SHARE * pl.col("n"))
        )
        .select("miner", "last_from")
        .sort("miner", "last_from")
    )


def block_classes(block_revenue: pl.DataFrame, last_tx: pl.DataFrame) -> pl.DataFrame:
    """One class per block, first match wins: empty (no transactions) -> paid (last transaction
    from the fee recipient) -> payout (last transaction from the miner's payout address, value > 0,
    to someone other than the miner) -> proposer_is_fee_recipient (the miner has no paid or payout
    block anywhere, so it is taken to be the proposer) -> unexplained. `payout_pair` marks blocks
    of a payout pair, which `class_counts` needs for top-ups."""
    df = block_revenue.select("block_number", "miner", "last_from", "last_value_wei").join(
        last_tx.select("block_number", "to_address", "receipt_gas_used"),
        on="block_number",
        how="left",
    )
    missing = df.filter(pl.col("last_from").is_not_null() & pl.col("receipt_gas_used").is_null())
    if missing.height:
        first_missing = missing.sort("block_number")["block_number"][0]
        raise ValueError(f"block {first_missing} has transactions but no last_tx row")
    pairs = payout_pairs(block_revenue).with_columns(payout_pair=pl.lit(True))
    df = df.join(pairs, on=["miner", "last_from"], how="left").with_columns(
        pl.col("payout_pair").fill_null(False)
    )
    payout = (
        pl.col("payout_pair")
        & (pl.col("last_value_wei") > 0)
        & pl.col("to_address").is_not_null()
        & (pl.col("to_address") != pl.col("miner"))
    )
    first = (
        pl.when(pl.col("last_from").is_null())
        .then(pl.lit(EMPTY))
        .when(pl.col("last_from") == pl.col("miner"))
        .then(pl.lit(PAID))
        .when(payout)
        .then(pl.lit(PAYOUT))
    )
    return (
        df.with_columns(cls=first)
        .with_columns(pays=pl.col("cls").is_in([PAID, PAYOUT]).any().over("miner"))
        .with_columns(
            cls=pl.when(pl.col("cls").is_not_null())
            .then(pl.col("cls"))
            .when(~pl.col("pays"))
            .then(pl.lit(PROPOSER_IS_FEE_RECIPIENT))
            .otherwise(pl.lit(UNEXPLAINED))
        )
        .drop("pays")
        .sort("block_number")
    )


def class_counts(classes: pl.DataFrame) -> dict[str, int]:
    """Blocks per class, plus `n_top_up`: payout-pair blocks whose last transaction goes to the
    fee recipient itself (the builder topping up its payout address, not paying a proposer)."""
    counts = {c: int((classes["cls"] == c).sum()) for c in CLASSES}
    top_up = classes["payout_pair"] & (classes["to_address"] == classes["miner"])
    return {**counts, "n_top_up": int(top_up.sum())}
