# Validation report: **PASS**

- generated_utc: `2026-10-14T16:25:22+00:00`
- git_commit: `e69f749`
- window: `[2026-07-01, 2026-10-01)`
- snapshot_block: `25433938`
- snapshot_fee_protocol: `68`
- input_sha256_16: `{'raw/pool_logs_2026-07-01_2026-08-01.parquet': 'd63cecd2087cf703', 'raw/pool_logs_2026-08-01_2026-09-01.parquet': '969de26de6bbddd1', 'raw/pool_logs_2026-09-01_2026-10-01.parquet': '4219a9635468c2cb', 'raw/tickbook_snapshot.parquet': 'ccaa9baa98726baf', 'raw/snapshot_meta.json': '3b93b79ce12ca7b0', 'raw/onchain_sample_ticks.parquet': 'b0e8c024793beb26', 'raw/onchain_samples.parquet': 'd0c103ee0ba63119', 'raw/binance/ETHUSDC-aggTrades-2026-07.zip': 'c921f1d08e49cb19', 'raw/binance/ETHUSDC-aggTrades-2026-08.zip': 'c1ce03be89ddb1ce', 'raw/binance/ETHUSDC-aggTrades-2026-09.zip': 'e86dd47bd5dffe00', 'raw/binance/ETHUSDT-1s-2026-07.zip': '093f882bd1c0bea9', 'raw/binance/ETHUSDT-1s-2026-08.zip': 'cf65149d610676dc', 'raw/binance/ETHUSDT-1s-2026-09.zip': 'aecc6196852931e5', 'interim/cex_ethusdc.parquet': '2bb21f2bb6ca55b8', 'interim/cex_ethusdt_1s.parquet': '02a5ea793a51eea0', 'interim/events.parquet': 'fcb1cfcb7c07a6e7', 'interim/swaps.parquet': 'b5a3ddae03e7f7d2'}`

| Check | Result | Summary |
|---|---|---|
| C1 active liquidity per swap | PASS | swaps=534377, mismatches=0 |
| C2 tick vs sqrt price | PASS | swaps=534377, mismatches=0, boundary_cases=2 |
| C3 on-chain samples | PASS | blocks=500, expected_blocks=500, full_book_blocks=5, expected_full_book_blocks=5, blocks_missing_data=0, ticks_compared=17625, mismatches=0 |
| C4 snapshot self-consistency | PASS | initialized_ticks=1557, sum_liquidity_net=0, rebuilt_active=2811825879343074188, onchain_liquidity=2811825879343074188 |
| C5 raw data integrity | PASS | logs=556664, duplicates=0, unjoined_tx=0, outside_window=0, other_events=0, binance_files=6, bad_checksums=[], max_binance_trade_gap_s=169.371924 |
| C6 pool vs Binance sanity | PASS | swaps=534377, matched=534377, unmatched=0, median_bp=3.757092918929006, p95_bp=6.655944897718813, bound_bp=10.0 |
