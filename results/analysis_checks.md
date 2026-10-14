# Analysis checks: **PASS**

- generated_utc: `2026-10-14T16:25:31+00:00`
- git_commit: `e69f749-dirty`
- input_sha256_16: `{'interim/cex_ethusdc.parquet': '2bb21f2bb6ca55b8', 'interim/cex_ethusdt_1s.parquet': '02a5ea793a51eea0', 'interim/events.parquet': 'fcb1cfcb7c07a6e7', 'interim/swaps.parquet': 'b5a3ddae03e7f7d2', 'raw/tickbook_snapshot.parquet': 'ccaa9baa98726baf', 'raw/snapshot_meta.json': '3b93b79ce12ca7b0', 'raw/blocks.parquet': '0026aebc769e72fd', 'raw/bot_tx_other_logs.parquet': 'f24f64f92d41ff77', 'raw/bot_transfers/0x149d330c8b9352573d17bc184b7a426ea020b38e.parquet': '6ec48b3108d16d0d', 'raw/bot_transfers/0x51c72848c68a965f66fa7a88855f9f7784502a7f.parquet': '4709759d4749f96e', 'raw/bot_transfers/0xbdb3ba9ffe392549e1f8658dd2630c141fdf47b6.parquet': 'f64808538b447479', 'raw/bot_transfers/0xeff6cb8b614999d130e537751ee99724d01aa167.parquet': '44e8dce9e7b7a224', 'labels/addresses.csv': '90715e75b8d28b72'}`

| Check | Result | Summary |
|---|---|---|
| A1 v3swap reproduces every swap | PASS | swaps=534377, bit_exact=496936, outside_tolerance=0, no_input_skipped=0, max_sqrt_rel_err=1.1148429016363366e-14, max_out_abs_err=632735604 |
| A2 block series complete and consistent | PASS | blocks=659799, expected_blocks=659799, missing=0, duplicates=0, block_table_starts_at_first_block=True, start_differs_from_previous_end=0, end_differs_from_last_swap=0, idle_blocks_changed=0, last_block_within_one_slot_of_window_end=True, blocks_cover_last_event=True |
| A3 trader + LP + protocol fee = 0 | PASS | values_checked=2671386, unevaluated=0, max_abs_residual_usd=6.991740519879386e-12, tolerance_usd=1e-06 |
| A4 Binance reference coverage | PASS | null_0s=0, unexpected_null_0s=0, null_12s=0, unexpected_null_12s=0, null_60s=10, unexpected_null_60s=0, null_300s=35, unexpected_null_300s=0, null_3600s=454, unexpected_null_3600s=0, stale_ref_over_5s_at_0s=73139 |
| A5 label coverage (reported) | PASS | other_contract_notional_share=0.10897229175784204, by_label={'searcher': 0.747554137005692, 'uniswap_router': 0.11604430840941152, 'other_contract': 0.10897229175784204, 'aggregator': 0.022448011851733847, 'intent_settlement': 0.004981250975320495} |
| A6 builder payments (reported) | PASS | top_bot_txs=110989, transfers_to_miner=56724, transfers_to_others=6, txs_with_coinbase_payment=56724, share_txs_with_coinbase_payment=0.5110776743641262, top_bot_txs_without_scope=0 |

## A5 label coverage (reported): details

```
{'address': '0x8f40082c34812db98681c63db3bbeb29dbe871a7', 'swaps': 2460, 'notional_usd': 129314737.64324899}
{'address': '0xccc88a9d1b4ed6b0eaba998850414b24f1c315be', 'swaps': 13309, 'notional_usd': 38266665.044631995}
{'address': '0x709de0b97e369661c99ad54f2b858139897d3dba', 'swaps': 9177, 'notional_usd': 31617353.642219}
{'address': '0x07964f135f276412b3182a3b2407b8dd45000000', 'swaps': 1040, 'notional_usd': 24554470.872640997}
{'address': '0xd22ae3a7696dc76d99b37fa299b93c6794afeb66', 'swaps': 572, 'notional_usd': 24241607.958738}
```
