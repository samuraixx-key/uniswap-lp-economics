# Where LVR goes

Every figure here counts every searcher step, including steps with no liquidity in range; the accrued-only `*_searcher_usd` totals in lp_pnl.md and summary.json do not. Shares are of LVR on searcher steps.

A payout address is a sender other than the fee recipient that sent the last transaction in at least 50 of the fee recipient's blocks, with value > 0 in at least 99% of them. Blocks left unexplained: 0.73% of blocks and 0.04% of single-pool builder dollars ($630.11); they give the proposer the whole builder revenue.

The split of builder payments between builder and proposer uses each block's ratio of proposer payment to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments are identified as the block's last transaction, sent by the fee recipient or by a payout address learned from chain data, and tested on a blind stratified relay sample; blocks where neither applies give the proposer the whole builder revenue.

## Totals

| metric | value |
|---|---|
| pool_lvr_0_usd | 3,703,796.7593 |
| share_searcher_of_pool_lvr | 1.1189 |
| lvr_on_searcher_swaps_usd | 4,144,118.0034 |
| lvr_on_other_flows_usd | -440,321.2441 |
| fees_on_searcher_swaps_usd | 1,976,144.8452 |
| protocol_fees_on_searcher_swaps_usd | 658,714.8663 |
| searcher_gross_usd | 1,509,258.2919 |
| multi_pool_gross_usd | 257,681.7252 |
| single_pool_gross_usd | 1,251,576.5667 |
| gas_burned_usd | 9,715.8891 |
| builder_margin_usd | 848,648.0888 |
| proposer_usd | 594,782.4656 |
| searcher_kept_usd | -201,569.8769 |
| share_fees | 0.4769 |
| share_protocol_fees | 0.1590 |
| share_multi_pool | 0.0622 |
| share_gas_burned | 0.0023 |
| share_builder_margin | 0.2048 |
| share_proposer | 0.1435 |
| share_searcher_kept | -0.0486 |
| n_searcher_swaps | 253,280 |
| n_swaps_no_other_logs_row | 0 |
| n_swaps_block_not_in_split | 0 |
| n_swaps_null_costs | 0 |

## Block classes

| cls | blocks | share_blocks | builder_paid_usd | share_builder_paid_usd |
|---|---|---|---|---|
| empty | 175 | 0.00 | 0.00 | 0.00 |
| paid | 554,263 | 0.84 | 1,146,073.18 | 0.79 |
| payout | 44,073 | 0.07 | 296,703.85 | 0.21 |
| proposer_is_fee_recipient | 56,501 | 0.09 | 23.42 | 0.00 |
| unexplained | 4,787 | 0.01 | 630.11 | 0.00 |

## Payout recipients

| type | payments | blocks | paid_eth | builder_paid_usd |
|---|---|---|---|---|
| wallet | 9,272 | 9,272 | 175.46 | 59,269.43 |
| 7702_wallet | 0 | 0 | 0.00 | 0.00 |
| contract | 34,801 | 34,801 | 677.73 | 237,434.42 |

## Seed-45 holdout (R1d)

| metric | value |
|---|---|
| bar | 0.9500 |
| n_found_payout | 290 |
| one_split | True |
| recipient_check | R1d |
| round | holdout2 |
| share_recipient_match | 1.0000 |
| share_within_1_wei | 1.0000 |
| share_within_1pct | 1.0000 |
