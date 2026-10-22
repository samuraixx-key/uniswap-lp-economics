# Strategy checks: **PASS**

- generated_utc: `2026-10-22T15:59:23+00:00`
- git_commit: `forwarder-preregistered-38-gc5f5e90-dirty`

| Check | Result | Summary |
|---|---|---|
| S2 identity replay | PASS | blocks_compared=659799, steps_compared=586360, swaps_compared=534377, mismatches=0, first_mismatch=None |
| S1 range attribution vs engine | PASS | positions=7874, max_rel_error_fee=5.893329713124729e-10, max_rel_error_lvr=9.44269171535006e-10, failures=0, worst_position=direct:0x1f2f10d1c40777ae1da742455c65828ff36df387:197420:197430:11 |
| S3 calibration (July, frozen) | reported | fee_ratio=1.0549969155468955, fee_ratio_1s=1.0731486988993635, lvr_ratio=1.3795718316146928, lvr_ratio_1s=1.3284889006720721, measured_fee_usd=746409.1200712873, measured_lvr_usd=1094192.8119730572, model_fee_usd=787459.3194112804, model_lvr_usd=1509517.5817533017, passed=False, replaced_swaps=33507, tolerance=0.15 |
| Size flags (peak share of active liquidity above 5%) | reported | flagged_rows=46, max_peak_share_1m=0.8382511932605593 |
| Sandwich legs among replaced swaps | reported | legs=135, gross_usd=-711.5499235056344, notional_share=0.0034458638293508553, non_top_legs=100, non_top_gross_usd=-3390.173305595257 |
| Counterfactual pool counts | reported | runs=34, july_runs={'model_0s': {'arb_trades': 34433, 'below_min_profit': 4337, 'mode_exact_input': 101928, 'mode_exact_output': 9925, 'mode_to_price': 988, 'no_input': 0, 'no_reference_blocks': 0, 'replaced': 33507, 'to_price_skipped': 245, 'unreproduced': 0}, 'model_1s': {'arb_trades': 34717, 'below_min_profit': 4245, 'mode_exact_input': 101928, 'mode_exact_output': 9925, 'mode_to_price': 1073, 'no_input': 0, 'no_reference_blocks': 1, 'replaced': 33507, 'to_price_skipped': 160, 'unreproduced': 0}} |

## Size flags (peak share of active liquidity above 5%): details

```
{'strategy': 'static_10bp', 'capital': 1000000.0, 'peak_share': 0.7537864534174918}
{'strategy': 'static_25bp', 'capital': 1000000.0, 'peak_share': 0.6049456063411216}
{'strategy': 'static_50bp', 'capital': 1000000.0, 'peak_share': 0.45527245029202995}
{'strategy': 'static_100bp', 'capital': 1000000.0, 'peak_share': 0.30475191283527475}
{'strategy': 'static_250bp', 'capital': 1000000.0, 'peak_share': 0.15338024216159246}
{'strategy': 'static_500bp', 'capital': 1000000.0, 'peak_share': 0.08429303066610867}
{'strategy': 'static_2500bp', 'capital': 1000000.0, 'peak_share': 0.05158241045934564}
{'strategy': 'out_of_range_10bp', 'capital': 1000000.0, 'peak_share': 0.8316713893815219}
{'strategy': 'out_of_range_25bp', 'capital': 1000000.0, 'peak_share': 0.7570436428928189}
{'strategy': 'out_of_range_50bp', 'capital': 1000000.0, 'peak_share': 0.6621112062280328}
{'strategy': 'out_of_range_100bp', 'capital': 1000000.0, 'peak_share': 0.5237755445441927}
{'strategy': 'out_of_range_250bp', 'capital': 1000000.0, 'peak_share': 0.3203389319523675}
{'strategy': 'out_of_range_500bp', 'capital': 1000000.0, 'peak_share': 0.1950517020883011}
{'strategy': 'out_of_range_1000bp', 'capital': 1000000.0, 'peak_share': 0.11179398181070527}
{'strategy': 'out_of_range_2500bp', 'capital': 1000000.0, 'peak_share': 0.05158241045934564}
{'strategy': 'band_10bp', 'capital': 1000000.0, 'peak_share': 0.8225920827308972}
{'strategy': 'band_25bp', 'capital': 1000000.0, 'peak_share': 0.7488746597431682}
{'strategy': 'band_50bp', 'capital': 1000000.0, 'peak_share': 0.6410866385404027}
{'strategy': 'band_100bp', 'capital': 1000000.0, 'peak_share': 0.5205418677075265}
{'strategy': 'band_250bp', 'capital': 1000000.0, 'peak_share': 0.32384130012048506}
{'strategy': 'band_500bp', 'capital': 1000000.0, 'peak_share': 0.19839425656549373}
{'strategy': 'band_1000bp', 'capital': 1000000.0, 'peak_share': 0.11339093663908041}
{'strategy': 'band_2500bp', 'capital': 1000000.0, 'peak_share': 0.05162061504302167}
{'strategy': 'daily_10bp', 'capital': 1000000.0, 'peak_share': 0.8382511932605593}
{'strategy': 'daily_25bp', 'capital': 1000000.0, 'peak_share': 0.6612533500471687}
{'strategy': 'daily_50bp', 'capital': 1000000.0, 'peak_share': 0.5184892290022823}
{'strategy': 'daily_100bp', 'capital': 1000000.0, 'peak_share': 0.4235906746908454}
{'strategy': 'daily_250bp', 'capital': 1000000.0, 'peak_share': 0.25281449958418706}
{'strategy': 'daily_500bp', 'capital': 1000000.0, 'peak_share': 0.1719409810378059}
{'strategy': 'daily_1000bp', 'capital': 1000000.0, 'peak_share': 0.1083452564537641}
{'strategy': 'daily_2500bp', 'capital': 1000000.0, 'peak_share': 0.05148769115640909}
{'strategy': 'static_10bp', 'capital': 100000.0, 'peak_share': 0.23439202578495022}
{'strategy': 'static_25bp', 'capital': 100000.0, 'peak_share': 0.13279486225141138}
{'strategy': 'static_50bp', 'capital': 100000.0, 'peak_share': 0.07713151241655775}
{'strategy': 'out_of_range_10bp', 'capital': 100000.0, 'peak_share': 0.33069003784266776}
{'strategy': 'out_of_range_25bp', 'capital': 100000.0, 'peak_share': 0.23757042900525546}
{'strategy': 'out_of_range_50bp', 'capital': 100000.0, 'peak_share': 0.16384839061886255}
{'strategy': 'out_of_range_100bp', 'capital': 100000.0, 'peak_share': 0.09908693775741535}
{'strategy': 'band_10bp', 'capital': 100000.0, 'peak_share': 0.31678714855155465}
{'strategy': 'band_25bp', 'capital': 100000.0, 'peak_share': 0.22970712972919335}
{'strategy': 'band_50bp', 'capital': 100000.0, 'peak_share': 0.15154923388801972}
{'strategy': 'band_100bp', 'capital': 100000.0, 'peak_share': 0.09793599302175453}
{'strategy': 'daily_10bp', 'capital': 100000.0, 'peak_share': 0.3413437276060776}
{'strategy': 'daily_25bp', 'capital': 100000.0, 'peak_share': 0.16332405664385571}
{'strategy': 'daily_50bp', 'capital': 100000.0, 'peak_share': 0.09721192563559018}
{'strategy': 'daily_100bp', 'capital': 100000.0, 'peak_share': 0.06845706400563618}
```

## Counterfactual pool counts: details

```
{'rule': 'fixed_1bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 235, 'no_input': 0, 'to_price_skipped': 2692, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 237887, 'below_min_profit': 43637, 'no_reference_blocks': 0}
{'rule': 'fixed_2.5bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 404, 'no_input': 0, 'to_price_skipped': 2523, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 163485, 'below_min_profit': 27909, 'no_reference_blocks': 0}
{'rule': 'fixed_5bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2394, 'no_input': 0, 'to_price_skipped': 533, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 99997, 'below_min_profit': 15992, 'no_reference_blocks': 0}
{'rule': 'fixed_7.5bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2441, 'no_input': 0, 'to_price_skipped': 486, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 69380, 'below_min_profit': 10842, 'no_reference_blocks': 0}
{'rule': 'fixed_10bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2283, 'no_input': 0, 'to_price_skipped': 644, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 53157, 'below_min_profit': 8006, 'no_reference_blocks': 0}
{'rule': 'fixed_15bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2043, 'no_input': 0, 'to_price_skipped': 884, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 36196, 'below_min_profit': 5411, 'no_reference_blocks': 0}
{'rule': 'fixed_20bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1947, 'no_input': 0, 'to_price_skipped': 980, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 27480, 'below_min_profit': 4123, 'no_reference_blocks': 0}
{'rule': 'fixed_30bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1854, 'no_input': 0, 'to_price_skipped': 1073, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 18509, 'below_min_profit': 2788, 'no_reference_blocks': 0}
{'rule': 'fixed_50bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1796, 'no_input': 0, 'to_price_skipped': 1131, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 11170, 'below_min_profit': 1670, 'no_reference_blocks': 0}
{'rule': 'fixed_100bp', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1789, 'no_input': 0, 'to_price_skipped': 1138, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 5267, 'below_min_profit': 862, 'no_reference_blocks': 0}
{'rule': 'vol_k1_h25', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 729, 'no_input': 0, 'to_price_skipped': 2198, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 178909, 'below_min_profit': 40751, 'no_reference_blocks': 0}
{'rule': 'vol_k1_h150', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 787, 'no_input': 0, 'to_price_skipped': 2140, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 166979, 'below_min_profit': 35742, 'no_reference_blocks': 0}
{'rule': 'vol_k1_h900', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 750, 'no_input': 0, 'to_price_skipped': 2177, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 156179, 'below_min_profit': 30342, 'no_reference_blocks': 0}
{'rule': 'vol_k2_h25', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1388, 'no_input': 0, 'to_price_skipped': 1539, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 132273, 'below_min_profit': 32697, 'no_reference_blocks': 0}
{'rule': 'vol_k2_h150', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1626, 'no_input': 0, 'to_price_skipped': 1301, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 115801, 'below_min_profit': 26393, 'no_reference_blocks': 0}
{'rule': 'vol_k2_h900', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1926, 'no_input': 0, 'to_price_skipped': 1001, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 103591, 'below_min_profit': 19821, 'no_reference_blocks': 0}
{'rule': 'vol_k4_h25', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2012, 'no_input': 0, 'to_price_skipped': 915, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 89765, 'below_min_profit': 22209, 'no_reference_blocks': 0}
{'rule': 'vol_k4_h150', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2146, 'no_input': 0, 'to_price_skipped': 781, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 72208, 'below_min_profit': 16032, 'no_reference_blocks': 0}
{'rule': 'vol_k4_h900', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2240, 'no_input': 0, 'to_price_skipped': 687, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 60752, 'below_min_profit': 11029, 'no_reference_blocks': 0}
{'rule': 'move_k0.5', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2482, 'no_input': 0, 'to_price_skipped': 445, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 94927, 'below_min_profit': 14634, 'no_reference_blocks': 0}
{'rule': 'move_k1', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2499, 'no_input': 0, 'to_price_skipped': 428, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 88914, 'below_min_profit': 13218, 'no_reference_blocks': 0}
{'rule': 'move_k2', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2496, 'no_input': 0, 'to_price_skipped': 431, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 82567, 'below_min_profit': 12204, 'no_reference_blocks': 0}
{'rule': 'move_k4', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2501, 'no_input': 0, 'to_price_skipped': 426, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 77924, 'below_min_profit': 10945, 'no_reference_blocks': 0}
{'rule': 'oracle', 'ref_offset_s': 0.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1791, 'no_input': 0, 'to_price_skipped': 1136, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 5291, 'below_min_profit': 854, 'no_reference_blocks': 0}
{'rule': 'fixed_1bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 200, 'no_input': 0, 'to_price_skipped': 2727, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 238677, 'below_min_profit': 43874, 'no_reference_blocks': 1}
{'rule': 'fixed_2.5bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 310, 'no_input': 0, 'to_price_skipped': 2617, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 164384, 'below_min_profit': 28107, 'no_reference_blocks': 1}
{'rule': 'fixed_5bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2532, 'no_input': 0, 'to_price_skipped': 395, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 100548, 'below_min_profit': 15910, 'no_reference_blocks': 1}
{'rule': 'fixed_7.5bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2447, 'no_input': 0, 'to_price_skipped': 480, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 69731, 'below_min_profit': 10709, 'no_reference_blocks': 1}
{'rule': 'fixed_10bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2302, 'no_input': 0, 'to_price_skipped': 625, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 53381, 'below_min_profit': 7947, 'no_reference_blocks': 1}
{'rule': 'fixed_15bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 2053, 'no_input': 0, 'to_price_skipped': 874, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 36229, 'below_min_profit': 5340, 'no_reference_blocks': 1}
{'rule': 'fixed_20bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1942, 'no_input': 0, 'to_price_skipped': 985, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 27467, 'below_min_profit': 4095, 'no_reference_blocks': 1}
{'rule': 'fixed_30bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1858, 'no_input': 0, 'to_price_skipped': 1069, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 18405, 'below_min_profit': 2698, 'no_reference_blocks': 1}
{'rule': 'fixed_50bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1791, 'no_input': 0, 'to_price_skipped': 1136, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 11033, 'below_min_profit': 1627, 'no_reference_blocks': 1}
{'rule': 'fixed_100bp', 'ref_offset_s': 1.0, 'mode_exact_input': 405879, 'mode_exact_output': 25681, 'mode_to_price': 1790, 'no_input': 0, 'to_price_skipped': 1137, 'unreproduced': 0, 'replaced': 99890, 'arb_trades': 5190, 'below_min_profit': 840, 'no_reference_blocks': 1}
```
