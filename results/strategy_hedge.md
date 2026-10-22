# Perp delta hedge: the risk lever (August-September, $1M)

Counterfactual: holds other traders' behaviour fixed; they would react to a different range, fee or hedge.

The hedge changes the spread of daily P&L, not fees - LVR.

| strategy | rule | taker_fee_bp | bp_per_day | sd_daily_usd_per_1m | mean_daily_usd_per_1m |
|---|---|---|---|---|---|
| full_range | never | 0.0000 | 30.0629 | 16,396.8621 | 3,355.0390 |
| full_range | daily | 5.0000 | 0.1531 | 466.0288 | 17.0848 |
| full_range | daily | 1.0000 | 0.2001 | 465.7746 | 22.3355 |
| full_range | daily | 10.0000 | 0.0943 | 468.3047 | 10.5214 |
| full_range | hourly | 5.0000 | 0.4107 | 160.2931 | 45.8324 |
| full_range | hourly | 1.0000 | 0.5143 | 155.7447 | 57.4013 |
| full_range | hourly | 10.0000 | 0.2811 | 171.1636 | 31.3713 |
| full_range | drift | 5.0000 | -1.6268 | 1,770.0725 | -181.5470 |
| full_range | drift | 1.0000 | -1.5903 | 1,769.5515 | -177.4775 |
| full_range | drift | 10.0000 | -1.6723 | 1,771.2705 | -186.6340 |
| full_range | rebalancing_benchmark |  | -0.1875 | 39.0770 | -20.9199 |
| band_5000bp | never | 0.0000 | 26.7313 | 13,828.3062 | 2,920.0490 |
| band_5000bp | daily | 5.0000 | 0.0130 | 2,409.9879 | 1.4171 |
| band_5000bp | daily | 1.0000 | 0.1267 | 2,411.3960 | 13.8393 |
| band_5000bp | daily | 10.0000 | -0.1292 | 2,408.6897 | -14.1106 |
| band_5000bp | hourly | 5.0000 | -1.0010 | 605.8119 | -109.3421 |
| band_5000bp | hourly | 1.0000 | -0.6203 | 587.8245 | -67.7592 |
| band_5000bp | hourly | 10.0000 | -1.4768 | 630.0859 | -161.3207 |
| band_5000bp | drift | 5.0000 | -1.2199 | 1,724.9056 | -133.2588 |
| band_5000bp | drift | 1.0000 | -1.1466 | 1,710.2118 | -125.2541 |
| band_5000bp | drift | 10.0000 | -1.3115 | 1,743.8239 | -143.2646 |
| band_5000bp | rebalancing_benchmark |  | -0.8688 | 179.3203 | -94.9006 |
