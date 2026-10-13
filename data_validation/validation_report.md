# Validation report: **PASS**

- generated_utc: `2026-10-13T20:54:17+00:00`
- git_commit: `e084739`
- window: `[2026-07-01, 2026-10-01)`
- snapshot_block: `25433938`
- snapshot_fee_protocol: `68`
- input_sha256_16: `{'pool_logs_2026-07-01_2026-08-01.parquet': 'd63cecd2087cf703', 'pool_logs_2026-08-01_2026-09-01.parquet': '969de26de6bbddd1', 'pool_logs_2026-09-01_2026-10-01.parquet': '4219a9635468c2cb'}`

| Check | Result | Summary |
|---|---|---|
| C1 active liquidity per swap | PASS | swaps=534377, mismatches=0 |
| C2 tick vs sqrt price | PASS | swaps=534377, mismatches=0, boundary_cases=2 |
| C3 on-chain samples | PASS | blocks=500, full_book_blocks=5, ticks_compared=17625, mismatches=0 |
| C4 snapshot self-consistency | PASS | initialized_ticks=1557, sum_liquidity_net=0, rebuilt_active=2811825879343074188, onchain_liquidity=2811825879343074188 |
| C5 raw data integrity | PASS | logs=556664, duplicates=0, unjoined_tx=0, outside_window=0, other_events=0, binance_files=6, bad_checksums=[], max_binance_trade_gap_s=169.371924 |
| C6 pool vs Binance sanity | PASS | swaps=534377, median_bp=3.757092918929006, p95_bp=6.655944897718813, bound_bp=10.0 |
