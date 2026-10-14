"""Arbitrage costs and net profit (spec 5.5).

Per transaction: gas burned (base fee), priority fee and direct coinbase payments, valued at the
Binance price at the block time and split across the transaction's swaps in our pool by
notional. Builder payments are only observed for the top bot contracts; elsewhere they are null.
"""

from typing import Any

import polars as pl

SINGLE_POOL = "single_pool"
MULTI_POOL = "multi_pool"
WEI = 1e18
_COSTS = ["gas_burned_usd", "priority_fee_usd", "coinbase_usd"]


def tx_scope(other_logs: pl.DataFrame) -> pl.DataFrame:
    """single_pool when a top-bot transaction emits no log outside pool/USDC/WETH/the bot."""
    return other_logs.select(
        "tx_hash",
        tx_scope=pl.when(pl.col("other_logs") == 0)
        .then(pl.lit(SINGLE_POOL))
        .otherwise(pl.lit(MULTI_POOL)),
    ).unique("tx_hash", keep="first", maintain_order=True)


def coinbase_payments(transfers: pl.DataFrame, blocks: pl.DataFrame) -> pl.DataFrame:
    """Per transaction: wei the top-bot contracts sent to the block's fee recipient."""
    joined = transfers.join(blocks.select("block_number", "miner"), on="block_number", how="inner")
    return (
        joined.filter(pl.col("to_address") == pl.col("miner"))
        .group_by("tx_hash")
        .agg(coinbase_wei=pl.col("value_wei").sum())
    )


def add_costs(
    aligned: pl.DataFrame,
    blocks: pl.DataFrame,
    transfers: pl.DataFrame,
    scope: pl.DataFrame,
    bots: list[str],
) -> pl.DataFrame:
    a = (
        aligned.join(
            blocks.select("block_number", "base_fee_per_gas"),
            on="block_number",
            how="left",
            maintain_order="left",
        )
        .join(coinbase_payments(transfers, blocks), on="tx_hash", how="left", maintain_order="left")
        .join(scope, on="tx_hash", how="left", maintain_order="left")
    )
    tx_notional = pl.col("notional_usd").sum().over("tx_hash")
    share = (
        pl.when(tx_notional > 0)
        .then(pl.col("notional_usd") / tx_notional)
        .otherwise(1.0 / pl.len().over("tx_hash"))
    )
    eth_usd = pl.col("p_cex_0") / WEI
    gas = pl.col("receipt_gas_used").cast(pl.Float64)
    base = pl.col("base_fee_per_gas").cast(pl.Float64)
    effective = pl.col("receipt_effective_gas_price").cast(pl.Float64)
    is_top = (pl.col("flow_label") == "searcher") & pl.col("sender").is_in(bots)
    coinbase = pl.col("coinbase_wei").cast(pl.Float64).fill_null(0.0)
    return a.with_columns(
        is_top_bot=is_top,
        gas_burned_usd=gas * base * eth_usd * share,
        priority_fee_usd=gas * (effective - base) * eth_usd * share,
        coinbase_usd=pl.when(is_top).then(coinbase * eth_usd * share),
        tx_scope=pl.when(is_top).then(pl.col("tx_scope")),
    ).drop("coinbase_wei")


def bot_profit_table(aligned: pl.DataFrame) -> pl.DataFrame:
    """Per top bot and in total: single-pool gross (0s markout) minus gas burned, priority fee
    and coinbase payments = kept; multi-pool transactions reported gross only."""
    bots = aligned.filter(pl.col("is_top_bot"))
    single = (
        bots.filter(pl.col("tx_scope") == SINGLE_POOL)
        .group_by("sender")
        .agg(
            swaps=pl.len().cast(pl.Int64),
            txs=pl.col("tx_hash").n_unique().cast(pl.Int64),
            txs_with_coinbase=pl.col("tx_hash")
            .filter(pl.col("coinbase_usd") > 0)
            .n_unique()
            .cast(pl.Int64),
            notional_usd=pl.col("notional_usd").sum(),
            gross_usd=pl.col("markout_usd_0").sum(),
            **{c: pl.col(c).sum() for c in _COSTS},
        )
    )
    multi = (
        bots.filter(pl.col("tx_scope") == MULTI_POOL)
        .group_by("sender")
        .agg(
            multi_pool_swaps=pl.len().cast(pl.Int64),
            multi_pool_gross_usd=pl.col("markout_usd_0").sum(),
        )
    )
    per_bot = (
        single.join(multi, on="sender", how="full", coalesce=True)
        .fill_null(0)
        .sort(["gross_usd", "sender"], descending=[True, False])
    )
    total = per_bot.select(pl.lit("TOTAL").alias("sender"), pl.exclude("sender").sum())
    table = pl.concat([per_bot, total], how="vertical_relaxed")
    builder = pl.col("priority_fee_usd") + pl.col("coinbase_usd")
    return table.with_columns(
        kept_usd=pl.col("gross_usd") - pl.col("gas_burned_usd") - builder,
        builder_usd=builder,
        builder_share_of_gross=pl.when(pl.col("gross_usd") > 0).then(builder / pl.col("gross_usd")),
        share_txs_with_coinbase=pl.when(pl.col("txs") > 0).then(
            pl.col("txs_with_coinbase") / pl.col("txs")
        ),
    )


def waterfall(series: pl.DataFrame, aligned: pl.DataFrame) -> dict[str, float]:
    """available (all blocks) -> captured by searchers -> top-bot single-pool gross -> kept.

    Gross is the 0 s markout. Because kept is a small difference of large totals, its sign depends
    on the horizon, so the same costs are also netted against the 12 s markout (`*_12s_usd`).
    """

    def total(df: pl.DataFrame, col: str) -> float:
        return float(df[col].sum())

    single = aligned.filter(pl.col("is_top_bot") & (pl.col("tx_scope") == SINGLE_POOL))
    gross = total(single, "markout_usd_0")
    gross_12s = total(single, "markout_usd_12")
    burned = total(single, "gas_burned_usd")
    priority = total(single, "priority_fee_usd")
    coinbase = total(single, "coinbase_usd")
    result: dict[str, Any] = {
        "available_usd": total(series, "available_usd"),
        "available_cex1bp_usd": total(series, "available_usd_cex1bp"),
        "captured_searchers_usd": total(
            aligned.filter(pl.col("flow_label") == "searcher"), "markout_usd_0"
        ),
        "top_bot_single_pool_gross_usd": gross,
        "gas_burned_usd": burned,
        "priority_fee_usd": priority,
        "coinbase_usd": coinbase,
        "kept_usd": gross - burned - priority - coinbase,
        "top_bot_single_pool_gross_12s_usd": gross_12s,
        "kept_12s_usd": gross_12s - burned - priority - coinbase,
    }
    return result
