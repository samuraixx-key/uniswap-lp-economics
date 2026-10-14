# LP P&L: fees vs LVR

P&L against rebalancing = fees - LVR (0 s) - LP gas; against holding = everything the LP got out minus everything put in, at the exit price. bp_per_day = P&L / (hourly time-weighted position value x days). Intervals: 95% bootstrap over positions (1,000 resamples, seed 42).

## Window totals

| metric | value |
|---|---|
| lp_fees_usd | 2,644,187.1709 |
| protocol_fees_usd | 881,290.1312 |
| lvr_0_usd | 3,703,796.7593 |
| lvr_12_usd | 4,089,325.4866 |
| lvr_0_searcher_usd | 4,144,118.0034 |
| lp_fees_searcher_usd | 1,976,144.8452 |
| theory_1s_usd | 3,158,845.5113 |
| theory_1m_usd | 4,333,659.2365 |
| theory_arb_usd | 933,257.6717 |
| theory_arb_fees_usd | 2,225,587.8396 |
| positions_window_active | 7,874 |
| pnl_rebal_total_usd | -1,087,478.4579 |
| pnl_hold_total_usd | -18,208,565.5233 |
| share_positions_beat_hold_window | 0.2409 |
| zero_liquidity_steps | 0 |
| steps_without_12s_reference | 0 |
| collect_shortfalls.count | 2,622 |
| collect_shortfalls.max_d0 | 48 |
| collect_shortfalls.max_d1 | 44 |
| noop_collects | 179 |
| n_excluded_carry | 0 |
| fees_minus_lvr_usd | -1,059,609.5884 |

## By LP type

| grouping | group | positions | fees_usd | lvr_0_usd | gas_usd | pnl_rebal_usd | pnl_hold_usd | share_beat_hold | bp_per_day | ci_lo_bp | ci_hi_bp | bp_per_day_hold |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lp_type | jit | 844 | 4,752.92 | -28,934.84 | 19,771.41 | 13,916.34 | 13,916.34 | 0.57 | 5,629.54 | 1,240.38 | 10,381.09 | 5,629.54 |
| lp_type | lp_vault | 111 | 12,151.37 | 15,643.43 | 176.30 | -3,668.37 | -20,529.53 | 0.32 | -1.58 | -3.05 | -1.21 | -8.83 |
| lp_type | nft_wallet | 5,788 | 2,572,025.84 | 3,644,992.64 | 5,495.25 | -1,078,462.06 | -18,127,230.35 | 0.19 | -1.35 | -1.77 | -1.12 | -22.75 |
| lp_type | nft_contract | 734 | 38,156.22 | 50,739.87 | 1,717.36 | -14,301.02 | -74,523.43 | 0.19 | -2.28 | -2.77 | -1.91 | -11.90 |
| lp_type | direct_other | 397 | 17,100.83 | 21,355.65 | 708.54 | -4,963.36 | -198.55 | 0.38 | -1.55 | -2.12 | -1.08 | -0.06 |
