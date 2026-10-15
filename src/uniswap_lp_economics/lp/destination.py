"""Where LVR goes (spec section 7): LVR on searcher steps -> LP fees, protocol fees and the
searchers' gross; single-pool gross -> gas burned, builder margin, proposer payment, kept."""

from typing import Any

import polars as pl

from uniswap_lp_economics.lp.pnl import tx_receipts

LIMITATION_TEXT = (
    "The split of builder payments between builder and proposer uses each block's ratio of "
    "proposer payment to builder revenue; how a builder prices an individual transaction is not "
    "observed. Proposer payments are identified as the block's last transaction from the fee "
    "recipient and cross-checked against relay data on a sample of blocks only."
)
SINGLE, MULTI = "single_pool", "multi_pool"
WEI = 1e18
SELF_BUILT_SHARE_BASIS = (
    "volume-weighted over paid blocks: sum of proposer payments / sum of builder revenue"
)


def block_split(block_revenue: pl.DataFrame) -> pl.DataFrame:
    """Builder revenue R_b and proposer payment Q_b per block. Without a payment transaction (the
    block's last transaction is not from the fee recipient) the block is classed self-built: the
    fee recipient is taken to be the proposer and Q_b = R_b. That is the primary method. The relay
    sample shows that most such blocks are in fact MEV-Boost blocks that pay the proposer some
    other way (a payment not in the last transaction, or from a separate payout address), so
    `destination` also reports a sensitivity with these blocks at the paid-block share."""
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


def paid_block_ratio(split: pl.DataFrame) -> float:
    """Proposer share of builder revenue over the blocks with a payment transaction, weighted by
    revenue: sum(Q_b) / sum(R_b). Volume-weighted because what is split is a sum of USD: each wei
    of builder revenue counts once, and a block with almost no revenue (whose per-block share
    can be huge when the builder subsidises the proposer) cannot pull the ratio."""
    paid = split.filter(~pl.col("self_built"))
    revenue = float(paid["revenue_wei"].cast(pl.Float64).sum()) if paid.height else 0.0
    if revenue <= 0:
        return 0.0
    return float(paid["payment_wei"].cast(pl.Float64).sum()) / revenue


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
    s = (
        aligned.filter(pl.col("flow_label") == "searcher")
        .join(tx_receipts(events), on="tx_hash", how="left")
        .join(blocks.select("block_number", "base_fee_per_gas"), on="block_number", how="left")
        .join(tx_direct, on="tx_hash", how="left")
        .join(tx_other_logs.select("tx_hash", "other_logs"), on="tx_hash", how="left")
        .join(
            split.select("block_number", "proposer_share", "self_built"),
            on="block_number",
            how="left",
        )
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


def sensitivity_self_built(
    single: pl.DataFrame, split: pl.DataFrame, lvr_searcher: float
) -> dict[str, Any]:
    """The proposer/builder split again, with self-built blocks at the paid-block proposer share
    (`paid_block_ratio`) instead of 1. Only the split between proposer and builder margin moves;
    their sum, gas, kept and every other destination are unchanged."""
    ratio = paid_block_ratio(split)
    sb = pl.col("self_built").fill_null(False)
    in_sb = single.filter(sb)
    paid = float(single["builder_paid_usd"].sum()) if single.height else 0.0
    paid_sb = float(in_sb["builder_paid_usd"].sum()) if in_sb.height else 0.0
    proposer_primary = float(single["proposer_usd"].sum()) if single.height else 0.0
    proposer_primary_sb = float(in_sb["proposer_usd"].sum()) if in_sb.height else 0.0
    proposer = proposer_primary - proposer_primary_sb + ratio * paid_sb
    margin = paid - proposer
    n_sb = int(split["self_built"].sum()) if split.height else 0
    paid_blocks = split.filter(~pl.col("self_built") & (pl.col("revenue_wei") > 0))

    def share(value: float) -> float:
        return value / lvr_searcher if lvr_searcher else 0.0

    return {
        "self_built_proposer_share": ratio,
        "self_built_share_basis": SELF_BUILT_SHARE_BASIS,
        "median_paid_block_proposer_share": (
            float(paid_blocks["proposer_share"].median())  # type: ignore[arg-type]
            if paid_blocks.height
            else None
        ),
        "blocks": split.height,
        "self_built_blocks": n_sb,
        "share_blocks_self_built": n_sb / split.height if split.height else 0.0,
        "n_single_pool_swaps_self_built": in_sb.height,
        "builder_paid_usd": paid,
        "builder_paid_self_built_usd": paid_sb,
        "share_builder_paid_self_built": paid_sb / paid if paid else 0.0,
        "share_primary_proposer_in_self_built": (
            proposer_primary_sb / proposer_primary if proposer_primary else 0.0
        ),
        "proposer_usd": proposer,
        "builder_margin_usd": margin,
        "share_proposer": share(proposer),
        "share_builder_margin": share(margin),
    }


def destination(
    steps: pl.DataFrame, aligned: pl.DataFrame, costs: pl.DataFrame, split: pl.DataFrame
) -> dict[str, Any]:
    """Pool LVR (0 s) -> LVR on searcher steps -> where it goes, in USD and as shares of the LVR
    on searcher steps. Only steps labelled "searcher" count: flash-fee records carry the label
    "flash" (LVR 0) and belong to the other flows. Every searcher step counts here, also those
    with no liquidity in range (the summary's accrued-only `*_searcher_usd` keys do not).

    Chain: LVR on searcher steps = LP fees + protocol fees + searcher gross; gross = multi-pool
    gross + single-pool gross; single-pool gross = gas burned + builder margin + proposer + kept.
    The seven `share_*` values therefore sum to 1 when the first identity holds. The `n_*` counts
    say how many swaps were handled by a fallback in `searcher_costs`.

    The proposer/builder split is primary as `block_split` defines it (self-built blocks give
    the proposer everything); `sensitivity_self_built` holds the alternative split."""
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
        "sensitivity_self_built": sensitivity_self_built(single, split, lvr_searcher),
    }
