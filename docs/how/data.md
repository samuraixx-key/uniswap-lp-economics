# Data and validation

## Sources and collection

Study window: `[2026-07-01, 2026-10-01)` UTC. Pool: USDC/WETH 0.05%
(`0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`). Token0 is USDC (6 decimals), token1 is WETH
(18 decimals), fee 500 pips, tick spacing 10.

| Source | What | How |
|---|---|---|
| Uniswap V3 pool `0x88e6…5640` | All pool logs in the window (Swap, Mint, Burn, Collect, Flash, CollectProtocol), block timestamps, tx sender/recipient | BigQuery `bigquery-public-data.crypto_ethereum`, one file per month |
| Archive RPC | Full tick book at the snapshot block just before the window; pool state at 500 random blocks inside it | Starts the replay and validates it |
| Binance | ETHUSDC aggregated trades (one row per taker order at one price, µs timestamps; primary reference price) and ETHUSDT 1-second candles | [data.binance.vision](https://data.binance.vision), checksum-verified |

**What was collected.** 556,664 pool logs: 534,377 swaps, 5,616 mints, 8,115 burns, 8,119 collects,
57 flash and 380 collect_protocol. From Binance: 15,296,344 ETHUSDC trades and 7,948,800 ETHUSDT
1-second candles (complete).

**How liquidity is reconstructed.** Pool logs say what changed, not the full state, so the tick book
is rebuilt by replaying events in `(block, log_index)` order, starting from an on-chain snapshot of
the full tick book at block 25,433,938 (2026-06-30 23:59:59 UTC). State values (prices, liquidity)
are exact integers: Python `int` in code, `Int128` in Polars, and `Decimal(38, 0)` in the parquet
files (so pyarrow, pandas and DuckDB can read them too; use `uniswap_lp_economics.io.read_exact` to
get `Int128` back in Polars). Floats appear only in readable columns such as `amount_usdc`,
`amount_eth` and `price_usd`.

**Protocol fee.** Read from chain, `feeProtocol` is 68 (`0x44`) at the snapshot block and throughout
the window: the protocol takes 1/4 of every swap fee, in both tokens. There were no `SetFeeProtocol`
events in the window, and 380 `CollectProtocol` events. LP fee income in later stages therefore has
to be computed net of the protocol's quarter.

**Added for LP P&L (sub-project 3).** Positions open at the window start were created earlier, so
the pool's full history is needed to know their state and their LP:

| Source | What | How |
|---|---|---|
| Pool and NonfungiblePositionManager logs, 2021-05-04 to the window end | Every `Mint`/`Burn`/`Collect`, and the NFT positions' `IncreaseLiquidity`/`DecreaseLiquidity`/`Collect`/`Transfer` | BigQuery, one paid query (2.98 TB scanned) |
| Archive RPC | Fee-growth state at the snapshot and at the 500 sample blocks; every position's stored state at the window's start and end; whether each LP address has contract code | `eth_call` batched through Multicall3, `eth_getCode` |
| BigQuery transactions, traces and logs | Per block: builder revenue, proposer payment and the last transaction's recipient and gas; per transaction touching the pool: payments to the block's fee recipient and logs from other contracts | Aggregated inside BigQuery (about 676 GB scanned) |
| MEV-Boost relays | Relay-reported proposer payments for 1,000 random window blocks and two 600-block holdouts | Public data APIs, cross-check only |
| Binance | ETHUSDT 1-minute candles since the pool's creation | data.binance.vision, checksum-verified |
| `labels/lp_addresses.csv` | Four LP vaults named on Etherscan, with source links | Curated |

**Added for the strategy experiment (Phase 5).** Binance USDⓈ-M ETHUSDC perpetual funding rates
and 1-minute klines for July–September, from data.binance.vision, checksum-verified (the hedge
instrument). No new BigQuery query.

**Third-party data in the repository.** Two figure-data files, `results/figure_data/episode_cex.csv`
and the `p_cex` column of `episode_blocks.csv`, hold raw Binance trade prices from
data.binance.vision. They are Binance's data, included only to draw figure 2, and are not covered
by the repository's MIT licence. Every other file in `results/` holds derived statistics.

## Validation

Full report: [`data_validation/validation_report.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/data_validation/validation_report.md)
(machine-readable: `validation_report.json`, which also lists a SHA-256 prefix of every input file
and the git commit). Overall status: **PASS**.

| Check | What it compares | Result |
|---|---|---|
| C1 | Active liquidity from the replayed tick book vs the `liquidity` value emitted in each Swap event | 534,377 swaps, 0 mismatches |
| C2 | Each swap's reported tick vs the tick implied by its `sqrtPriceX96` | 534,377 swaps, 0 mismatches (2 of them stop exactly on a tick boundary) |
| C3 | Replayed state vs on-chain `slot0`, `liquidity()` and `ticks()` at 500 random blocks (5 of them with the full set of initialized ticks) | 500/500 blocks, 17,625 ticks compared, 0 mismatches, 0 blocks missing data |
| C4 | Snapshot self-consistency | 1,557 initialized ticks; `liquidity_net` sums to 0; rebuilt active liquidity 2,811,825,879,343,074,188 equals on-chain `liquidity()` |
| C5 | Raw data integrity | 556,664 logs, 0 duplicates, 0 without a transaction, 0 outside the window, 0 of unknown event type; 6 Binance files, no bad checksums |
| C6 | Pool price vs the last Binance ETHUSDC trade before each swap | 534,377/534,377 matched; median gap 3.757 bp (gated: must be below 10 bp); 95th percentile 6.656 bp (reported, not bounded) |

What this proves and what it does not:

- C1 and C3 are exact-integer comparisons. Together they show that our reconstruction of in-range
  liquidity matches the chain at every swap and at 500 randomly chosen blocks. The fee and LVR
  calculations depend on that. It is a statement about this pool and this window, not a general
  proof that the replay code is correct for other pools.
- C3 checks a sample of blocks and ticks (the 20 initialized ticks nearest the price at each block,
  taken from the on-chain bitmap, plus the full book at 5 blocks), not every tick at every block.
  C1 covers every swap; C3 checks more fields (ticks not crossed by swaps) at sampled blocks.
- The C6 median is a sanity bound that catches gross errors such as a wrong decimal or an inverted
  price. It is not a finding, and it says nothing about who gains or loses from the pool/CEX gap.
- C5 reports a longest gap of 169.371924 s between consecutive Binance ETHUSDC trades. That is a
  property of the data, not a defect, but the CEX price at a swap can be that stale in quiet periods.

Method summary: every definition and formula is in the [full methodology](methodology/index.md).

## 1. Data and validation

Inputs from sub-project 1, validated by checks C1–C6
([`data_validation/validation_report.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/data_validation/validation_report.md)): pool events and
swaps, the full tick book at snapshot block 25,433,938, Binance ETHUSDC trades and ETHUSDT 1-second
candles. Replaying the events from the snapshot gives the exact pool state before every event.

Added in sub-project 2 (all git-ignored under `DATA_DIR/raw`, except the labels):

| File | Source | Content |
|---|---|---|
| `blocks.parquet` | BigQuery `crypto_ethereum.blocks` | Every block in the window: number, timestamp, `miner` (the fee recipient), `base_fee_per_gas` |
| `bot_tx_other_logs.parquet` | BigQuery `transactions` joined to `logs` | Per transaction sent to a top bot: the number of logs emitted by any address other than the pool, USDC, WETH and the bot itself |
| `bot_transfers/<address>.parquet` | Alchemy `alchemy_getAssetTransfers`, `category=["internal"]`, `fromAddress` = the bot | Internal ETH transfers sent by each top bot contract; one cached file per contract (Ruling 4) |
| `labels/addresses.csv` (committed) | Curated (section 4) | Address labels |

Guards and provenance:

- `ulpe analyze` first calls `require_validated()`: the validation report must say PASS, and the
  SHA-256 prefix of every `interim/*` file it lists must match the file on disk.
- It then runs checks A1–A6 (section 8) and writes them to
  [`results/analysis_checks.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/analysis_checks.md). If a gated check (A1–A4) fails, it
  stops before writing any result.
- `results/summary.json` records the git commit and the SHA-256 prefix of every input file.
- Per-swap and per-block working tables go to `DATA_DIR/processed/aligned.parquet` (one row per
  swap, section 3) and `blocks_state.parquet` (one row per block, section 6).

The window holds 534,377 swaps with a total notional of 7,049,939,044.91 USD
([`results/markouts.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/markouts.md)) in 659,799 blocks.
