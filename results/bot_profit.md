# Top bots: gross vs kept

Builder payments are detected only as direct ETH transfers from the bot contract to the block's fee recipient within the same transaction. Payments routed elsewhere (another contract, a separate transaction in the bundle, off-chain agreements) are missed, so the reported net profit is an **upper bound** on what the bots keep. Binance-side trading fees, inventory and hedging costs are not observed.

| sender | swaps | txs | txs_with_coinbase | notional_usd | gross_usd | gas_burned_usd | priority_fee_usd | coinbase_usd | multi_pool_swaps | multi_pool_gross_usd | kept_usd | builder_usd | builder_share_of_gross | share_txs_with_coinbase |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0x51c72848c68a965f66fa7a88855f9f7784502a7f | 72,430 | 72,430 | 48,634 | 3,078,053,184.74 | 866,708.75 | 5,971.13 | 364,635.79 | 724,542.58 | 0 | 0.00 | -228,440.75 | 1,089,178.37 | 1.26 | 0.67 |
| 0xbdb3ba9ffe392549e1f8658dd2630c141fdf47b6 | 10,671 | 10,671 | 3,758 | 539,967,788.95 | 188,574.94 | 1,081.85 | 163,146.48 | 34,872.62 | 22,987 | 324,841.08 | -10,526.01 | 198,019.11 | 1.05 | 0.35 |
| 0x149d330c8b9352573d17bc184b7a426ea020b38e | 2,006 | 2,006 | 2,006 | 97,610,307.25 | 80,932.48 | 351.17 | 0.00 | 71,713.58 | 0 | 0.00 | 8,867.73 | 71,713.58 | 0.89 | 1.00 |
| 0xeff6cb8b614999d130e537751ee99724d01aa167 | 2,895 | 2,895 | 2,326 | 96,852,047.96 | 79,341.20 | 424.18 | 9,727.46 | 31,185.23 | 0 | 0.00 | 38,004.34 | 40,912.69 | 0.52 | 0.80 |
| TOTAL | 88,002 | 88,002 | 56,724 | 3,812,483,328.90 | 1,215,557.38 | 7,828.33 | 537,509.74 | 862,314.01 | 22,987 | 324,841.08 | -192,094.70 | 1,399,823.75 | 1.15 | 0.64 |
