# Fee level, dynamic fee and protocol cut (August-September)

Counterfactual: holds other traders' behaviour fixed; they would react to a different range, fee or hedge.

Fixed-volume shortcut: kept (non-arbitrage) flow is re-executed at its observed size at every fee. break_even_share beside each row is the share of that flow the pool could lose before the full-range LP is no better off than at 5 bp (removed flow's fees and LVR scale linearly; the price path does not change). The test (verdict) is on the arbitrage side only: arb_ratio and d_arb against the 5 bp model run, paired day bootstrap. bp_per_day of a fee rule: (fees - LVR) per unit of liquidity times the liquidity of the $1M full-range position, over that position's value in the real pool.

Model-only: calibration (S3) failed in July, so every fee result here is model-only and the fee test is not tested.

| rule | avg_fee_bp | arb_fee_bp | arb_ratio | d_arb | d_arb_lo | d_arb_hi | pool_ratio | break_even_share | ref_offset_s | verdict | bp_per_day |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fixed_1bp | 1.0000 | 1.0000 | 0.1199 | -0.2042 | -0.2251 | -0.1812 | 0.2205 | -1.2523 | 0.0000 | not tested (below baseline) | -0.6454 |
| fixed_2.5bp | 2.5000 | 2.5000 | 0.2270 | -0.0971 | -0.1065 | -0.0870 | 0.4440 | -0.5986 | 0.0000 | not tested (below baseline) | -0.4608 |
| fixed_5bp | 5.0000 | 5.0000 | 0.3241 | 0.0000 | 0.0000 | 0.0000 | 0.7002 | 0.0000 | 0.0000 | baseline | -0.2488 |
| fixed_7.5bp | 7.5000 | 7.5000 | 0.3807 | 0.0565 | 0.0522 | 0.0608 | 0.9120 | 0.3391 | 0.0000 | not tested (calibration failed) | -0.0732 |
| fixed_10bp | 10.0000 | 10.0000 | 0.4203 | 0.0962 | 0.0901 | 0.1028 | 1.1127 | 0.5363 | 0.0000 | not tested (calibration failed) | 0.0939 |
| fixed_15bp | 15.0000 | 15.0000 | 0.4749 | 0.1507 | 0.1432 | 0.1598 | 1.5054 | 0.7333 | 0.0000 | not tested (calibration failed) | 0.4220 |
| fixed_20bp | 20.0000 | 20.0000 | 0.5118 | 0.1877 | 0.1789 | 0.1975 | 1.8967 | 0.8226 | 0.0000 | not tested (calibration failed) | 0.7479 |
| fixed_30bp | 30.0000 | 30.0000 | 0.5589 | 0.2348 | 0.2245 | 0.2452 | 2.6820 | 0.8984 | 0.0000 | not tested (calibration failed) | 1.3990 |
| fixed_50bp | 50.0000 | 50.0000 | 0.6095 | 0.2853 | 0.2717 | 0.2972 | 4.2855 | 0.9493 | 0.0000 | not tested (calibration failed) | 2.6985 |
| fixed_100bp | 100.0000 | 100.0000 | 0.6624 | 0.3382 | 0.3211 | 0.3549 | 8.1898 | 0.9813 | 0.0000 | not tested (calibration failed) | 5.9242 |
| vol_k1_h25 | 2.2905 | 3.4169 | 0.3334 | 0.0093 | -0.0360 | 0.0540 | 0.7638 | 0.1037 | 0.0000 | reported in full (not tested) | -0.1974 |
| vol_k1_h150 | 2.5225 | 3.3351 | 0.3154 | -0.0087 | -0.0506 | 0.0329 | 0.7131 | 0.0202 | 0.0000 | reported in full (not tested) | -0.2394 |
| vol_k1_h900 | 2.7841 | 3.1974 | 0.2968 | -0.0273 | -0.0599 | 0.0015 | 0.6453 | -0.1087 | 0.0000 | reported in full (not tested) | -0.2954 |
| vol_k2_h25 | 4.0041 | 5.9769 | 0.4378 | 0.1137 | 0.0689 | 0.1579 | 1.1697 | 0.5509 | 0.0000 | reported in full (not tested) | 0.1418 |
| vol_k2_h150 | 4.5360 | 5.9823 | 0.4146 | 0.0905 | 0.0475 | 0.1329 | 1.0943 | 0.4928 | 0.0000 | reported in full (not tested) | 0.0787 |
| vol_k2_h900 | 5.1020 | 5.8352 | 0.3917 | 0.0675 | 0.0348 | 0.0971 | 0.9838 | 0.4006 | 0.0000 | reported in full (not tested) | -0.0135 |
| vol_k4_h25 | 7.0830 | 10.8429 | 0.5343 | 0.2101 | 0.1691 | 0.2490 | 1.7855 | 0.8029 | 0.0000 | reported in full (not tested) | 0.6547 |
| vol_k4_h150 | 8.1995 | 11.0868 | 0.5082 | 0.1840 | 0.1432 | 0.2253 | 1.6952 | 0.7769 | 0.0000 | reported in full (not tested) | 0.5794 |
| vol_k4_h900 | 9.3527 | 10.9353 | 0.4829 | 0.1588 | 0.1249 | 0.1905 | 1.5328 | 0.7311 | 0.0000 | reported in full (not tested) | 0.4456 |
| move_k0.5 | 5.3605 | 6.5159 | 0.4093 | 0.0852 | 0.0685 | 0.0995 | 0.9213 | 0.3662 | 0.0000 | reported in full (not tested) | -0.0652 |
| move_k1 | 5.7047 | 6.4459 | 0.3935 | 0.0694 | 0.0464 | 0.0903 | 1.0089 | 0.4441 | 0.0000 | reported in full (not tested) | 0.0074 |
| move_k2 | 6.3737 | 6.3357 | 0.3742 | 0.0501 | 0.0277 | 0.0738 | 1.1703 | 0.5371 | 0.0000 | reported in full (not tested) | 0.1424 |
| move_k4 | 7.6251 | 6.4161 | 0.3673 | 0.0432 | 0.0144 | 0.0735 | 1.4291 | 0.6388 | 0.0000 | reported in full (not tested) | 0.3626 |
| oracle | 37.8382 | 100.0000 | 0.6625 | 0.3383 | 0.3213 | 0.3551 | 4.4357 | 0.9629 | 0.0000 | oracle (not tested): arbitrage pays the 100 bp cap | 2.8309 |
| fixed_1bp | 1.0000 | 1.0000 | 0.1306 | -0.2149 | -0.2335 | -0.1939 | 0.2496 | -1.1225 | 1.0000 | sensitivity (+1 s) | -0.5516 |
| fixed_2.5bp | 2.5000 | 2.5000 | 0.2447 | -0.1008 | -0.1087 | -0.0918 | 0.4923 | -0.5418 | 1.0000 | sensitivity (+1 s) | -0.3819 |
| fixed_5bp | 5.0000 | 5.0000 | 0.3455 | 0.0000 | 0.0000 | 0.0000 | 0.7598 | 0.0000 | 1.0000 | sensitivity (+1 s) | -0.1846 |
| fixed_7.5bp | 7.5000 | 7.5000 | 0.4032 | 0.0577 | 0.0541 | 0.0614 | 0.9777 | 0.3185 | 1.0000 | sensitivity (+1 s) | -0.0174 |
| fixed_10bp | 10.0000 | 10.0000 | 0.4427 | 0.0972 | 0.0923 | 0.1029 | 1.1817 | 0.5087 | 1.0000 | sensitivity (+1 s) | 0.1431 |
| fixed_15bp | 15.0000 | 15.0000 | 0.4969 | 0.1514 | 0.1448 | 0.1591 | 1.5832 | 0.7070 | 1.0000 | sensitivity (+1 s) | 0.4638 |
| fixed_20bp | 20.0000 | 20.0000 | 0.5333 | 0.1878 | 0.1793 | 0.1968 | 1.9866 | 0.8007 | 1.0000 | sensitivity (+1 s) | 0.7861 |
| fixed_30bp | 30.0000 | 30.0000 | 0.5792 | 0.2337 | 0.2225 | 0.2447 | 2.7935 | 0.8823 | 1.0000 | sensitivity (+1 s) | 1.4319 |
| fixed_50bp | 50.0000 | 50.0000 | 0.6257 | 0.2801 | 0.2655 | 0.2934 | 4.4302 | 0.9378 | 1.0000 | sensitivity (+1 s) | 2.7230 |
| fixed_100bp | 100.0000 | 100.0000 | 0.6737 | 0.3282 | 0.3095 | 0.3456 | 8.3552 | 0.9741 | 1.0000 | sensitivity (+1 s) | 5.9379 |
| real_pool | 5.0000 |  | 0.4311 |  |  |  | 0.7550 |  |  | reference (real pool) | -0.1875 |
| protocol_cut_0 | 5.0000 |  |  |  |  |  | 1.0067 |  |  | arithmetic (not tested) | 0.0052 |
| protocol_cut_0.1 | 5.0000 |  |  |  |  |  | 0.9061 |  |  | arithmetic (not tested) | -0.0719 |
| protocol_cut_0.25 | 5.0000 |  |  |  |  |  | 0.7550 |  |  | arithmetic (not tested) | -0.1875 |
