"""Where LVR goes (spec section 7): LVR on searcher steps -> LP fees, protocol fees and the
searchers' gross; single-pool gross -> gas burned, builder margin, proposer payment, kept."""

from typing import Any

import polars as pl

LIMITATION_TEXT = (
    "The split of builder payments between builder and proposer uses each block's ratio of "
    "proposer payment to builder revenue; how a builder prices an individual transaction is not "
    "observed. Proposer payments are identified as the block's last transaction from the fee "
    "recipient and cross-checked against relay data on a sample of blocks only."
)
SINGLE, MULTI = "single_pool", "multi_pool"
WEI = 1e18


def block_split(block_revenue: pl.DataFrame) -> pl.DataFrame:
    """Builder revenue R_b and proposer payment Q_b per block. Without a payment transaction the
    fee recipient is the proposer (a self-built block) and Q_b = R_b."""
    revenue = pl.col("priority_wei") + pl.col("direct_wei")
    paid = pl.col("last_from") == pl.col("miner")
    return block_revenue.select(
        "block_number",
        "miner",
        revenue_wei=revenue,
        payment_wei=pl.when(paid).then(pl.col("last_value_wei")).otherwise(revenue),
        self_built=~paid.fill_null(False),
    ).with_columns(
        proposer_share=pl.when(pl.col("revenue_wei") > 0)
        .then(pl.col("payment_wei").cast(pl.Float64) / pl.col("revenue_wei").cast(pl.Float64))
        .otherwise(0.0)
    )


def searcher_costs(
    aligned: pl.DataFrame,
    events: pl.DataFrame,
    blocks: pl.DataFrame,
    tx_direct: pl.DataFrame,
    tx_other_logs: pl.DataFrame,
    split: pl.DataFrame,
) -> pl.DataFrame:
    """Per searcher swap: its share (by notional within the transaction) of gas burned and of
    the transaction's payment to the fee recipient, split into proposer and builder margin."""
    tx = events.group_by("tx_hash").agg(
        pl.col("receipt_gas_used").first(), pl.col("receipt_effective_gas_price").first()
    )
    s = (
        aligned.filter(pl.col("flow_label") == "searcher")
        .join(tx, on="tx_hash", how="left")
        .join(blocks.select("block_number", "base_fee_per_gas"), on="block_number", how="left")
        .join(tx_direct, on="tx_hash", how="left")
        .join(tx_other_logs.select("tx_hash", "other_logs"), on="tx_hash", how="left")
        .join(split.select("block_number", "proposer_share"), on="block_number", how="left")
    )
    tx_notional = pl.col("notional_usd").sum().over("tx_hash")
    share = (
        pl.when(tx_notional > 0)
        .then(pl.col("notional_usd") / tx_notional)
        .otherwise(1.0 / pl.len().over("tx_hash"))
    )
    usd = pl.col("p_cex_0") / WEI * share
    gas = pl.col("receipt_gas_used").cast(pl.Float64)
    base = pl.col("base_fee_per_gas").cast(pl.Float64)
    eff = pl.col("receipt_effective_gas_price").cast(pl.Float64)
    paid = gas * (eff - base) + pl.col("direct_wei").cast(pl.Float64).fill_null(0.0)
    out = s.with_columns(
        gross_usd=pl.col("markout_usd_0"),
        burned_usd=gas * base * usd,
        builder_paid_usd=paid * usd,
        scope=pl.when(pl.col("other_logs") == 0).then(pl.lit(SINGLE)).otherwise(pl.lit(MULTI)),
    ).with_columns(
        proposer_usd=pl.col("builder_paid_usd") * pl.col("proposer_share").fill_null(0.0),
    )
    return out.with_columns(
        builder_margin_usd=pl.col("builder_paid_usd") - pl.col("proposer_usd"),
        kept_usd=pl.col("gross_usd") - pl.col("burned_usd") - pl.col("builder_paid_usd"),
    )


def destination(steps: pl.DataFrame, aligned: pl.DataFrame, costs: pl.DataFrame) -> dict[str, Any]:
    """Pool LVR (0 s) -> LVR on searcher steps -> where it goes, in USD and as shares of the LVR
    on searcher steps. Only steps labelled "searcher" count: flash-fee records carry the label
    "flash" (LVR 0) and belong to the other flows. Every searcher step counts here, also those
    with no liquidity in range (the summary's accrued-only `*_searcher_usd` keys do not).

    Chain: LVR on searcher steps = LP fees + protocol fees + searcher gross; gross = multi-pool
    gross + single-pool gross; single-pool gross = gas burned + builder margin + proposer + kept.
    The seven `share_*` values therefore sum to 1 when the first identity holds. The `n_*` counts
    say how many swaps were handled by a fallback in `searcher_costs`."""
    searcher = pl.col("flow_label") == "searcher"
    single = costs.filter(pl.col("scope") == SINGLE)

    def total(df: pl.DataFrame, col: str) -> float:
        return float(df[col].sum()) if df.height else 0.0

    lvr_searcher = total(steps.filter(searcher), "lvr_0")
    lvr_other = total(steps.filter(~searcher), "lvr_0")
    pool_lvr = lvr_searcher + lvr_other
    parts = {
        "lvr_on_searcher_swaps_usd": lvr_searcher,
        "lvr_on_other_flows_usd": lvr_other,
        "fees_on_searcher_swaps_usd": total(steps.filter(searcher), "fee_usd"),
        "protocol_fees_on_searcher_swaps_usd": total(aligned.filter(searcher), "protocol_fee_usd"),
        "searcher_gross_usd": total(costs, "gross_usd"),
        "multi_pool_gross_usd": total(costs.filter(pl.col("scope") == MULTI), "gross_usd"),
        "single_pool_gross_usd": total(single, "gross_usd"),
        "gas_burned_usd": total(single, "burned_usd"),
        "builder_margin_usd": total(single, "builder_margin_usd"),
        "proposer_usd": total(single, "proposer_usd"),
        "searcher_kept_usd": total(single, "kept_usd"),
    }

    def share(value: float) -> float:
        return value / lvr_searcher if lvr_searcher else 0.0

    shares = {
        "share_fees": parts["fees_on_searcher_swaps_usd"],
        "share_protocol_fees": parts["protocol_fees_on_searcher_swaps_usd"],
        "share_multi_pool": parts["multi_pool_gross_usd"],
        "share_gas_burned": parts["gas_burned_usd"],
        "share_builder_margin": parts["builder_margin_usd"],
        "share_proposer": parts["proposer_usd"],
        "share_searcher_kept": parts["searcher_kept_usd"],
    }
    return {
        "pool_lvr_0_usd": pool_lvr,
        "share_searcher_of_pool_lvr": lvr_searcher / pool_lvr if pool_lvr else 0.0,
        **parts,
        **{k: share(v) for k, v in shares.items()},
        # Fallbacks in searcher_costs, counted instead of hidden (spec section 7).
        "n_searcher_swaps": costs.height,
        "n_swaps_no_other_logs_row": int(costs["other_logs"].is_null().sum()),
        "n_swaps_block_not_in_split": int(costs["proposer_share"].is_null().sum()),
        "n_swaps_null_costs": int(
            (costs["burned_usd"].is_null() | costs["builder_paid_usd"].is_null()).sum()
        ),
    }
