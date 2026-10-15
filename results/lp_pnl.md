# LP P&L: fees vs LVR

P&L against rebalancing = fees - LVR (0 s) - LP gas - direct payments to the fee recipient in the LP's transactions; against holding = everything the LP got out minus everything put in, at the exit price, less the same costs. bp_per_day = P&L / (hourly time-weighted position value x days). Intervals: 95% bootstrap over positions (1,000 resamples, seed 42).

JIT per swap: P&L of the jit positions divided by the swaps each was active for (swaps in its block between its first liquidity add and its last removal, in log order), summed over position-swap pairs; the median is over jit positions with at least one swap. Costs include direct payments to the fee recipient in the LP's transactions. Some JIT transactions also swap in the pool (jit_own_swaps in summary.json): a payment there may be for the swap, and the rebalancing benchmark takes those swaps as free.

## Window totals

| metric | value |
|---|---|
| lp_fees_usd | 2,644,187.1709 |
| protocol_fees_usd | 881,290.1312 |
| lvr_0_usd | 3,703,796.7593 |
| lvr_12_usd | 4,089,325.4866 |
| lvr_0_searcher_usd | 4,144,118.0034 |
| lp_fees_searcher_usd | 1,976,144.8452 |
| theory_1s_usd | 3,155,610.4780 |
| theory_1m_usd | 4,325,747.9614 |
| theory_arb_usd | 931,857.4744 |
| theory_arb_fees_usd | 2,223,753.0037 |
| positions_window_active | 7,874 |
| lp_gas_usd | 27,868.8695 |
| lp_direct_payments_usd | 10,357.8649 |
| pnl_rebal_total_usd | -1,097,836.3229 |
| pnl_hold_total_usd | -18,218,923.3882 |
| share_positions_beat_hold_window | 0.2407 |
| zero_liquidity_steps | 0 |
| steps_without_12s_reference | 0 |
| collect_shortfalls.count | 2,622 |
| collect_shortfalls.max_d0 | 48 |
| collect_shortfalls.max_d1 | 44 |
| noop_collects | 179 |
| n_excluded_carry | 0 |
| fees_minus_lvr_usd | -1,059,609.5884 |

## Daily series, with day-bootstrap intervals

| metric | value |
|---|---|
| days | 92 |
| days_lvr_above_lp_fees | 79 |
| days_lvr_above_total_fees | 41 |
| total_fees_usd | 3,525,477.3020 |
| fees_minus_lvr_usd | -1,059,609.5884 |
| total_fees_minus_lvr_usd | -178,319.4572 |
| bootstrap | 95%, 1000 resamples of days, seed 42 |
| fees_minus_lvr_ci_lo_usd | -1,533,757.9591 |
| fees_minus_lvr_ci_hi_usd | -712,591.7684 |
| total_fees_minus_lvr_ci_lo_usd | -566,463.7116 |
| total_fees_minus_lvr_ci_hi_usd | 91,433.7287 |

## By LP type

| grouping | group | positions | fees_usd | lvr_0_usd | gas_usd | direct_usd | pnl_rebal_usd | pnl_hold_usd | share_beat_hold | bp_per_day | ci_lo_bp | ci_hi_bp | bp_per_day_hold |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lp_type | jit | 844 | 4,752.92 | -28,934.84 | 19,771.41 | 10,353.71 | 3,562.64 | 3,562.63 | 0.57 | 1,441.18 | -754.71 | 3,555.89 | 1,441.18 |
| lp_type | lp_vault | 111 | 12,151.37 | 15,643.43 | 176.30 | 0.00 | -3,668.37 | -20,529.53 | 0.32 | -1.58 | -3.05 | -1.21 | -8.83 |
| lp_type | nft_wallet | 5,788 | 2,572,025.84 | 3,644,992.64 | 5,495.25 | 0.00 | -1,078,462.06 | -18,127,230.35 | 0.19 | -1.35 | -1.77 | -1.12 | -22.75 |
| lp_type | nft_contract | 734 | 38,156.22 | 50,739.87 | 1,717.36 | 0.06 | -14,301.08 | -74,523.49 | 0.19 | -2.28 | -2.77 | -1.91 | -11.90 |
| lp_type | direct_other | 397 | 17,100.83 | 21,355.65 | 708.54 | 4.09 | -4,967.46 | -202.64 | 0.38 | -1.55 | -2.12 | -1.08 | -0.06 |

## JIT per swap

| metric | value |
|---|---|
| positions | 844 |
| positions_with_swaps | 826 |
| swaps | 914 |
| fee_usd_per_swap | 5.2001 |
| lvr_0_usd_per_swap | -31.6574 |
| gas_usd_per_swap | 21.6317 |
| direct_usd_per_swap | 11.3279 |
| pnl_rebal_usd_per_swap | 3.8979 |
| pnl_hold_usd_per_swap | 3.8978 |
| median_pnl_rebal_usd_per_swap | 0.0906 |
