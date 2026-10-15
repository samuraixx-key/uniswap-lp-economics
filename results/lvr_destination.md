# Where LVR goes

Every figure here counts every searcher step, including steps with no liquidity in range; the accrued-only `*_searcher_usd` totals in lp_pnl.md and summary.json do not. Shares are of LVR on searcher steps.

The primary split treats a block whose last transaction is not from its fee recipient as self-built (proposer share 1). The relay sample shows that most such blocks are MEV-Boost blocks that paid the proposer some other way, so the sensitivity gives those blocks the volume-weighted proposer share of the paid blocks instead. Only proposer and builder margin move; their sum, and every other figure, is the same under both.

The split of builder payments between builder and proposer uses each block's ratio of proposer payment to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments are identified as the block's last transaction from the fee recipient and cross-checked against relay data on a sample of blocks only.

## Totals (primary split)

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
| builder_margin_usd | 654,139.4089 |
| proposer_usd | 789,291.1456 |
| searcher_kept_usd | -201,569.8769 |
| share_fees | 0.4769 |
| share_protocol_fees | 0.1590 |
| share_multi_pool | 0.0622 |
| share_gas_burned | 0.0023 |
| share_builder_margin | 0.1578 |
| share_proposer | 0.1905 |
| share_searcher_kept | -0.0486 |
| n_searcher_swaps | 253,280 |
| n_swaps_no_other_logs_row | 0 |
| n_swaps_block_not_in_split | 0 |
| n_swaps_null_costs | 0 |

## Sensitivity: self-built blocks at the paid-block proposer share

| metric | value |
|---|---|
| self_built_proposer_share | 0.4915 |
| self_built_share_basis | volume-weighted over paid blocks: sum of proposer payments / sum of builder revenue |
| median_paid_block_proposer_share | 0.6240 |
| blocks | 659,799 |
| self_built_blocks | 105,536 |
| share_blocks_self_built | 0.1600 |
| n_single_pool_swaps_self_built | 11,432 |
| builder_paid_usd | 1,443,430.5544 |
| builder_paid_self_built_usd | 297,357.3751 |
| share_builder_paid_self_built | 0.2060 |
| share_primary_proposer_in_self_built | 0.3767 |
| proposer_usd | 638,079.5347 |
| builder_margin_usd | 805,351.0198 |
| share_proposer | 0.1540 |
| share_builder_margin | 0.1943 |
