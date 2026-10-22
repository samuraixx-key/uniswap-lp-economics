# Pre-registered test (August-September)

Counterfactual: holds other traders' behaviour fixed; they would react to a different range, fee or hedge.

Model-only: calibration (S3) failed in July, so every fee result here is model-only and the fee test is not tested.

## Verdicts

| metric | value |
|---|---|
| delta | 0.0677 |
| r0 | 0.7292 |
| range_verdict | inconclusive |
| range_verdict_depends_on_flagged_cell | True |
| flagged_counted_cells | out_of_range_10bp, out_of_range_25bp, out_of_range_50bp, out_of_range_100bp, out_of_range_250bp, out_of_range_500bp, out_of_range_1000bp, out_of_range_2500bp, band_10bp, band_25bp, band_50bp, band_100bp, band_250bp, band_500bp, band_1000bp, band_2500bp, daily_10bp, daily_25bp, daily_50bp, daily_100bp, daily_250bp, daily_500bp, daily_1000bp, daily_2500bp |
| fee_verdict | not tested (calibration failed) |
| fee_model_only | True |
| lowest_holding_fee_bp |  |
| break_even_fee_bp_x | 8.5967 |
| volume_loss_share_at_x_y | 0.4256 |
| fee_level_verdicts.1bp | not tested (below baseline) |
| fee_level_verdicts.2.5bp | not tested (below baseline) |
| fee_level_verdicts.7.5bp | not tested (calibration failed) |
| fee_level_verdicts.10bp | not tested (calibration failed) |
| fee_level_verdicts.15bp | not tested (calibration failed) |
| fee_level_verdicts.20bp | not tested (calibration failed) |
| fee_level_verdicts.30bp | not tested (calibration failed) |
| fee_level_verdicts.50bp | not tested (calibration failed) |
| fee_level_verdicts.100bp | not tested (calibration failed) |
| best_strategy | band_5000bp |
