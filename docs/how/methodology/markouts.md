# Prices and markouts

## 2. Reference price and time zero

- **Reference.** `P_cex(t)` = price of the last Binance ETHUSDC trade with timestamp at or before
  `t` (microseconds). When several trades share a microsecond, the one with the highest Binance
  aggregated trade ID wins: `ulpe build` sorts the trades by timestamp and then trade ID, and the
  lookup takes the last of them. Such trades usually differ by a fraction of a basis point, but not
  always. Each lookup also stores the reference's age, `t` minus
  the time of that trade, in seconds. No order-book data exists for the window, so there is no mid
  price; the last trade stands in for it.
- **Time zero.** `t0 = block_timestamp`. Ethereum block timestamps are whole seconds; since the
  Merge, a block's timestamp is the start of its 12-second slot, and its contents are fixed close
  to that time. The bots' actual decision and hedge times are not observed, so `t0` is a
  convention; the `t0 − 2 s` robustness variant (section 3.4) measures how much it matters.
- **Horizons.** `h ∈ {0, 12, 60, 300, 3600}` seconds; the reference for horizon `h` is
  `P_cex(t0 + h)`.
- **Coverage (Ruling 6).** `P_cex(t)` is null when `t` is at or after the window end
  (2026-10-01 00:00 UTC, where the downloaded Binance data ends) or before the first trade. Using
  the data end rather than the last trade keeps a time after the data from silently taking a stale
  price. A swap whose reference at horizon `h` is null is left out of that horizon's statistics
  only. In this run: no null at 0 s and 12 s; 10 at 60 s, 35 at 300 s and 454 at 3,600 s, all past
  the data end. 73,139 swaps have a 0 s reference older than 5 s (check A4).

## 3. Markouts

### 3.1 Per swap (trader's side, USD)

`amount_usdc` and `amount_eth` are the pool's amounts in token units, positive = into the pool.
They include the swap fee, which V3 charges on the input token.

```
trader_markout_usd(h) = −( amount_usdc + amount_eth × P_cex(t0 + h) )
trader_markout_bp(h)  = trader_markout_usd(h) / notional_usd × 10⁴
protocol_fee_usd      = Σ_steps (fee_step // 4) in the input token, valued at P_cex(t0)
lp_markout_usd(h)     = −trader_markout_usd(h) − protocol_fee_usd
```

- A **positive trader markout** means the swap won against the pool at that horizon: what it
  received was worth more at Binance's price than what it paid, after the fee.
- `protocol_fee_usd` is the protocol's exact cut of the swap fee, in the input token. Each swap is
  re-run step by step through the V3 swap loop (`lp/swapfees.py`; check L1, "Changes in sub-project 3": every
  swap reproduces bit-exactly). The protocol takes `fee_step // 4` raw units of each step's fee,
  as the contract does (`feeProtocol` = 68 = `0x44` throughout the window, read from chain in
  sub-project 1). USDC is taken at face value, WETH at `P_cex(t0)`.
- The LP markout is the mirror image, net of the protocol's share of the fee, so
  trader + LP + protocol fee = 0 for every swap (check A3).
- **What the 0 s markout contains.** It includes the 0.05% fee and the swap's own price impact, so
  a swap with no information, at a pool price equal to Binance's, has a negative markout of about
  the fee plus its impact. Negative flow-level numbers are expected for uninformed flow; their size
  is what carries information.
- **Decomposition over horizons.**
  `trader_markout_usd(h) = trader_markout_usd(0) − amount_eth × (P_cex(t0 + h) − P_cex(t0))`. The
  0 s value is the execution edge against Binance at the block time; the change to a later horizon
  is the P&L of the ETH position the swap opened, if it were held unhedged.

### 3.2 `notional_usd`

`notional_usd = |amount_usdc|` (sub-project 1 carry-over item 3). It includes the fee on USDC-in
swaps (the fee is charged in USDC) and excludes it on USDC-out swaps (the fee is charged in WETH).
Used as the bp denominator, this asymmetry changes a markout by at most 0.05% of its own value
(0.0025 bp on a 5 bp markout). The column is left unchanged.

### 3.3 Aggregation and the day bootstrap

Groups: flow label (section 4); size bucket on `notional_usd` (`<1k`, `1k-10k`, `10k-100k`,
`>=100k` USD); flow label × size bucket; and all swaps. Per group and horizon
([`results/markouts.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/markouts.md)):

- `swaps`, `notional_usd` = Σ notional, `markout_usd` = Σ trader markout;
- `mean_bp = Σ markout_usd / Σ notional_usd × 10⁴`, the notional-weighted mean;
- `median_bp`, the unweighted median of per-swap `trader_markout_bp`. Many small swaps dominate it,
  so it can differ in sign from the weighted mean (for searchers at 0 s: median -0.57 bp, mean
  2.86 bp);
- `ci_lo_bp`, `ci_hi_bp`: a 95% interval for `mean_bp` from a bootstrap over UTC days.

The day bootstrap:

1. For the group and horizon, sum markout and notional per UTC day, over every day present in the
   whole table; a day on which the group did not trade contributes (0, 0).
2. Draw as many days as the table has, with replacement, 1,000 times (seed 42), and compute
   `Σ markout / Σ notional × 10⁴` on each resample.
3. The interval is the 2.5th to 97.5th percentile of these ratios.

Resampling whole days keeps the dependence within a day (volatility clusters, bot activity)
inside each draw; it treats days as independent of each other. A resample that draws no active day
for the group has no ratio and is dropped, so for a thin group (few active days) the interval is
conditional on at least one active day and can be narrow. Every group uses the same seed, so groups
share their resampled days: their intervals are comparable but not independent draws.

### 3.4 Robustness variants

[`results/markouts_robustness.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/markouts_robustness.md) re-runs the flow-label table
three more times:

1. `ethusdt_reference`: the reference is the ETHUSDT 1-second candle close. A candle's close is known
   only when the candle ends, so the close of the candle that opens at second `s` is stamped
   `s + 1`; the reference at `t` is the last stamped close at or before `t`. ETHUSDT is quoted in
   USDT and is not converted, so this variant also carries the USDT/USDC rate.
2. `t0_minus_2s`: `t0 = block_timestamp − 2 s`; every horizon moves with it.
3. `exclude_stale_over_5s`: the primary reference, without the 73,139 swaps whose 0 s reference is
   older than 5 s.

## 4. Flow labels

`labels/addresses.csv` has the columns `address, name, category, source_url, notes`. Allowed
categories: `uniswap_router`, `aggregator`, `intent_settlement`. Each address was checked against
official deployment docs or Etherscan's public label page, and `source_url` points to that page. On
load, the file is validated: lowercase `0x` + 40 hex, no duplicates, an allowed category, a
non-empty name and an `https://` source.

Each swap gets one label; the first matching rule wins. `sender` is the address that called the
pool (the Swap event's `sender`); `to_address` is the transaction's target.

1. `to_address` is in the CSV → its category.
2. `sender` is in the CSV → its category.
3. `sender == to_address` → `searcher`: a contract that is both the transaction's target and the
   pool's direct caller, the usual pattern of custom bot contracts. Any other contract used this
   way is labelled `searcher` too, and the label covers every strategy such contracts run, not
   only CEX-DEX arbitrage.
4. Otherwise → `other_contract`: the pool was called by an unlisted contract that is not the
   transaction's target (for example an unlisted router).

Each swap also gets a size bucket and `top_of_block` (`transaction_index ≤ 2`); `top_of_block` is
stored in `aligned.parquet` but not used in the published tables.

**Top bots.** Rank `searcher` senders by notional (ties by address) and take the smallest prefix
that covers at least 90% of `searcher` notional, capped at 25 contracts. In this window that is
four contracts (`top_bots` in `results/summary.json`). Builder payments are fetched for these
contracts only.

**Coverage** ([`results/labels_coverage.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/labels_coverage.md), check A5). The file
lists notional share by label and the 30 unlabelled (`other_contract`) senders and transaction
targets with the most notional. The two largest, the pool caller
`0x8f10b468b06c6fd214b65f87778827f7d113f996` (119,480,261.21 USD) and the transaction target
`0x8f40082c34812db98681c63db3bbeb29dbe871a7` (129,314,737.64 USD), are unverified contracts with no
public Etherscan name tag, so they stay `other_contract`.
