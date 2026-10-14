# Methodology: price discovery and markouts (sub-project 2)

This file defines every quantity in `results/` and gives its formula. Scope: the Uniswap V3
USDC/WETH 0.05% pool (`0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`) against Binance, window
`[2026-07-01, 2026-10-01)` UTC. The design spec is
[`docs/superpowers/specs/2026-10-13-price-discovery-markouts-design.md`](superpowers/specs/2026-10-13-price-discovery-markouts-design.md);
where the implementation plan amended it, the ruling is cited ("Ruling n"). Numbers quoted here
come from `results/`.

Notation: `f` = pool swap fee = 500 pips = 0.0005; `c` = Binance trading fee assumed for the
arbitrage (0 or 1 bp); `P_cex(t)` = reference price at time `t` (section 2); pool prices are in
USDC per WETH; 1 bp = 10⁻⁴.

Contents: [1 Data](#1-data-and-validation) · [2 Reference price](#2-reference-price-and-time-zero) ·
[3 Markouts](#3-markouts) · [4 Flow labels](#4-flow-labels) ·
[5 Costs](#5-costs-and-builder-payments) · [6 Price discovery](#6-price-discovery) ·
[7 Available arbitrage](#7-available-arbitrage) · [8 Checks](#8-checks-a1a6)

## 1. Data and validation

Inputs from sub-project 1, validated by checks C1–C6
([`data_validation/validation_report.md`](../data_validation/validation_report.md)): pool events and
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
  [`results/analysis_checks.md`](../results/analysis_checks.md). If a gated check (A1–A4) fails, it
  stops before writing any result.
- `results/summary.json` records the git commit and the SHA-256 prefix of every input file.
- Per-swap and per-block working tables go to `DATA_DIR/processed/aligned.parquet` (one row per
  swap, section 3) and `blocks_state.parquet` (one row per block, section 6).

The window holds 534,377 swaps with a total notional of 7,049,939,044.91 USD
([`results/markouts.md`](../results/markouts.md)) in 659,799 blocks.

## 2. Reference price and time zero

- **Reference.** `P_cex(t)` = price of the last Binance ETHUSDC trade with timestamp at or before
  `t` (microseconds). When several trades share a microsecond, the reference is an arbitrary one of
  them: `ulpe build` sorts the trades by timestamp with Polars' default (not order-preserving) sort,
  and the lookup then takes the last of them in that order. Such trades usually differ by a
  fraction of a basis point, but not always. Each lookup also stores the reference's age, `t` minus
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
protocol_fee_usd      = fee_usd × fee_protocol_share
lp_markout_usd(h)     = −trader_markout_usd(h) − protocol_fee_usd
```

- A **positive trader markout** means the swap won against the pool at that horizon: what it
  received was worth more at Binance's price than what it paid, after the fee.
- `fee_usd` is the fee in the input token, `ceil(amount_in × 500 / 10⁶)` raw units; USDC is
  taken at face value, WETH at the pre-swap pool price. `fee_protocol_share` is 1/4 throughout the
  window (`feeProtocol` = 68 = `0x44`, read from chain in sub-project 1).
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
([`results/markouts.md`](../results/markouts.md)):

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

[`results/markouts_robustness.md`](../results/markouts_robustness.md) re-runs the flow-label table
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

**Coverage** ([`results/labels_coverage.md`](../results/labels_coverage.md), check A5). The file
lists notional share by label and the 30 unlabelled (`other_contract`) senders and transaction
targets with the most notional. The two largest, the pool caller
`0x8f10b468b06c6fd214b65f87778827f7d113f996` (119,480,261.21 USD) and the transaction target
`0x8f40082c34812db98681c63db3bbeb29dbe871a7` (129,314,737.64 USD), are unverified contracts with no
public Etherscan name tag, so they stay `other_contract`.

## 5. Costs and builder payments

Per transaction, in USD at `P_cex(t0)`:

```
gas_burned_usd   = gas_used × base_fee_per_gas / 10¹⁸ × P_cex(t0)
priority_fee_usd = gas_used × (effective_gas_price − base_fee_per_gas) / 10¹⁸ × P_cex(t0)
coinbase_usd     = Σ internal transfers from the bot contract to the block's miner in this tx / 10¹⁸ × P_cex(t0)
```

- `gas_used` and `effective_gas_price` are the receipt fields of BigQuery `transactions`, fetched
  with the pool logs in sub-project 1; `base_fee_per_gas` and `miner` come from `blocks.parquet`.
- `miner` is the block's fee recipient. Under MEV-Boost this is usually the block builder, which
  pays the proposer separately; that split is not measured. "Builder income" below means income of
  the fee recipient.
- **Allocation.** When a transaction contains several swaps in our pool, its costs are split across
  them by notional share (equally if their total notional is 0).
- Gas costs are computed for every swap. Coinbase payments are observed only for the top bots; for
  other swaps they are null.
- Costs are found through the pool's Swap logs, so a bot transaction that reverts or exits without
  trading in the pool is not seen and its gas is not counted. This makes `kept` below an upper bound
  on this count too.

**Single-pool vs multi-pool.** A top-bot transaction is `single_pool` (classic CEX-DEX arbitrage)
when every log it emits comes from our pool, USDC, WETH or the bot contract itself, i.e. its count
in `bot_tx_other_logs.parquet` is 0; otherwise it is `multi_pool`. Single-pool transactions get the
full breakdown ([`results/bot_profit.md`](../results/bot_profit.md), per bot and TOTAL):

```
gross                  = Σ trader_markout_usd(0)
kept                   = gross − gas_burned − priority_fee − coinbase
builder income         = priority_fee + coinbase
builder_share_of_gross = builder income / gross
```

Multi-pool transactions are reported gross only (`multi_pool_swaps`, `multi_pool_gross_usd`): their
costs also pay for trades in other pools and cannot be split per pool. `txs_with_coinbase` counts
single-pool transactions that carry a coinbase payment; `share_txs_with_coinbase` =
`txs_with_coinbase / txs` (null when `txs` is 0).

The net ratio reported (`kept_over_top_bot_gross` in
[`results/arbitrage.md`](../results/arbitrage.md), and `kept_over_top_bot_gross_12s` against the
12 s markout) is `kept / top-bot single-pool gross`: numerator and denominator cover the same
transactions. The spec's `kept / captured` would divide the top bots' single-pool result by all
searchers' 0 s markouts, mixing two populations, so it is not reported.

Required limitation text (also in the README, `results/arbitrage.md` and `results/bot_profit.md`):

> Builder payments are detected only as direct ETH transfers from the bot contract to the block's fee recipient within the same transaction. Payments routed elsewhere (another contract, a separate transaction in the bundle, off-chain agreements) are missed, so the reported net profit is an **upper bound** on what the bots keep. Binance-side trading fees, inventory and hedging costs are not observed.

How to read `kept`. Gross is the 0 s markout: the swap valued at Binance's last trade at the block
timestamp. That is the edge measurable at block time, not the bots' realised hedge. `kept` is a
small difference of large totals, so its sign depends on the horizon: with the same costs, `kept`
is −$0.19M at the 0 s markout and +$0.06M at 12 s (builder income 115% vs 95% of gross; gross
$1.22M vs $1.47M; `kept_usd` and `kept_12s_usd` in
[`results/arbitrage.md`](../results/arbitrage.md)). A negative `kept` therefore does not show that
the bots lose money:

1. The bots' own hedge price and timing are not observed, and the measured edge depends on `t0`:
   the searcher 0 s markout is 1.80 bp with `t0 − 2 s`, 2.86 bp at `t0` and 3.58 bp at 12 s.
2. Binance-side fees, inventory and hedging are not observed.
3. "Upper bound" in the limitation text refers to missed builder payments (payments routed
   elsewhere would make net profit lower still), not to the gross measurement.

## 6. Price discovery

### 6.1 Block series

One row per block in the window (`blocks_state.parquet`, 659,799 blocks), from the same replay:
the pool's `sqrt_price_x96`, tick and liquidity at block start (the state after the previous
block's last event, carried through blocks without pool events) and at block end; `P_cex` at the
block timestamp and its age; event and swap counts.

```
basis_bp = ln(P_pool_start / P_cex(block_timestamp)) × 10⁴
```

Positive basis = ETH is dearer in the pool than on Binance.

### 6.2 Basis distribution

[`results/basis.md`](../results/basis.md): the mean and the 1, 5, 25, 50, 75, 95 and 99%
quantiles of `basis_bp` and `|basis_bp|`, and the share of blocks with `|basis_bp| > 5`. 5 bp is
the fee band: inside it, an arbitrage at the block-start price loses money before gas (section 7).

### 6.3 Gap episodes and closers

- An episode is a maximal run of consecutive blocks with `|basis_bp| > k`, for `k` = 5 bp (primary)
  and 10 bp. Runs are taken over consecutive rows of the block series, which check A2 shows has no
  missing block.
- Per episode ([`results/episodes.csv`](../results/episodes.csv)): start and end block, number of
  blocks, `duration_s` = time from the first to the last block's timestamp plus the interval from
  the last block to the next one (a one-block episode lasts one block interval, usually 12 s),
  peak `|basis_bp|`, and `gap_weight = Σ |basis_bp| × block seconds`.
- **Closer.** Let `e` be the episode's last block; block `e+1` starts inside the band.
  - A flow label, if at least one swap in `e` reduced `|ln(P_pool / P_cex(t_e))|` from its
    pre-swap to its post-swap price: the closer is the label of the swap that reduced it most. A
    swap that overshoots through `P_cex` counts only if the absolute log gap still shrinks.
  - `cex`, if no swap in `e` reduced the gap: Binance moved back toward the pool.
  - `open`, if `e` is the window's last block.
- Outputs ([`results/episodes.md`](../results/episodes.md)): per closer, the count and share of
  episodes, the gap weight and its share, and the median duration; a survival curve of durations.

The closer is the swap in `e` that moved the pool furthest toward Binance; it need not have closed
the gap on its own. At 12-second resolution, a `cex` close can be any Binance move back within the
block interval.

### 6.4 Lead-lag and AR(1) half-life

Per-block log returns:

```
r_pool[b] = ln(P_pool_start[b+1] / P_pool_start[b])     the move made by block b's events
r_cex[b]  = ln(P_cex(t[b+1]) / P_cex(t[b]))             Binance's move between block timestamps
xcorr(lag) = corr(r_pool[b], r_cex[b − lag]),  lag = −5 … +5 blocks
```

A positive lag means Binance moved first. At lag +1 the pool's move in block `b` is compared with
Binance's move over `[t[b−1], t[b]]`, the interval just before block `b`'s timestamp, i.e. the
information available when block `b` is built. Results:
[`results/leadlag.md`](../results/leadlag.md).

AR(1), by OLS over consecutive blocks:

```
basis[b+1] = α + φ · basis[b] + ε
half_life_blocks = ln(0.5) / ln(φ)          (defined for 0 < φ < 1)
half_life_s      = half_life_blocks × median block interval
```

This fits one linear decay rate to all blocks. Inside the fee band no arbitrage pulls the basis
back, so the decay is not the same everywhere; the half-life is a summary, not a model of the
arbitrage.

## 7. Available arbitrage

At each block start, against `P = P_cex(block_timestamp)`, with `f` = 0.0005 and `c` = 0 or 1 bp
(Ruling 1):

```
if P_pool < P·(1−f)·(1−c):  buy ETH from the pool (USDC in) until P_pool = P·(1−f)·(1−c)
                            profit = ETH_out × P × (1−c) − USDC_in
if P_pool > P·(1+c)/(1−f):  sell ETH into the pool (WETH in) until P_pool = P·(1+c)/(1−f)
                            profit = USDC_out − ETH_in × P × (1+c)
otherwise:                  0
```

Why these targets: when buying ETH, only `(1−f)` of each USDC paid enters the curve, so the
marginal cost of ETH is `P_pool / (1−f)`; it sells on Binance for `P·(1−c)`. Trading stops where the
two are equal, `P_pool = P·(1−f)·(1−c)`. Selling is symmetric: the marginal proceeds are
`P_pool·(1−f)` against a Binance cost of `P·(1+c)`. Ruling 1 made the spec's defining sentence
("marginal price after the fee equals `P_cex`") binding and corrected its inverted example
formulas; a unit test checks that this amount maximises profit.

**Exact simulation (Ruling 2).** `v3swap` is an exact-integer port of the V3 swap (SqrtPriceMath,
SwapMath.computeSwapStep, tick-bitmap word stepping and the pool's swap loop) over the replayed
tick book. `arb_to_price` runs an exact-input swap with the target as the price limit, crossing
initialized ticks and applying their liquidity changes; amounts stay exact integers until the
final conversion to USD. Check A1 shows the same code reproduces every historical swap.

Outputs ([`results/arbitrage.md`](../results/arbitrage.md)): `available_usd` (`c` = 0) and
`available_cex1bp_usd` (`c` = 1 bp), summed over all blocks and per UTC day.

Assumptions and what they mean for the total:

- no gas, unlimited Binance depth at the last trade price, and a Binance fee of 0 or 1 bp;
- the arbitrage is the first trade in the block, at the block-start state; other swaps in the block
  and competition between bots are ignored;
- the opportunity is measured at every block start along the realised path, so a gap that stays
  open for several blocks is counted at each block start. The total is a sum of per-block snapshots,
  not the amount one arbitrageur could have taken.

**Captured** = Σ `trader_markout_usd(0)` over all `searcher` swaps in the window. It is not a subset
of available: it also includes searchers trading after other swaps in the same block (gaps the
block-start state does not show) and searcher strategies other than CEX-DEX arbitrage. On some days
captured exceeds available (the "By day" table). `captured_over_available` is a ratio of two totals,
not a capture rate.

The waterfall (chart 4) runs: available → captured (all searchers) → top-bot single-pool gross →
minus gas burned → minus priority fee → minus coinbase payment → kept.

## 8. Checks A1–A6

Written to [`results/analysis_checks.md`](../results/analysis_checks.md) (and `.json`) before any
result. A1–A4 are gated: a failure stops `ulpe analyze` before it writes results. A5 and A6 are
reported. All six pass in this run.

**A1: `v3swap` reproduces every historical swap.** From the replayed state just before each swap,
an exact-input simulation with the event's input amount and direction must match the event's
output amount and final `sqrtPriceX96`. Tolerance (Ruling 2, amended twice during
implementation): final `sqrtPriceX96` relative error < 1e-9, and output within
`max(2 raw units, 1e-9 × |out|, 2 raw input units valued at the pre-swap pool price)`. The event
does not record whether the call was exact-input or exact-output, nor its price limit; exact-output
swaps round their input up by about one raw unit, and for dust swaps that rounding is the whole
input, which the third term covers. Result: 534,377 swaps, 496,936 bit-exact, 0 outside tolerance;
the largest `sqrtPriceX96` relative error is 1.1148429016363366e-14, the largest output difference
632,735,604 raw units (wei, under 1e-9 ETH).
*Proves:* the simulator and the replayed liquidity agree with the chain at every swap, so the
available-arbitrage amounts rest on the right state. *Does not prove:* the target-price logic of
section 7, which is unit-tested.

**A2: block series complete and consistent (Ruling 3).** Every block from 25,433,939 to the
window's last block is present once; each block's start state equals the previous block's end
state; each block's end price equals its last swap's `sqrtPriceX96`; blocks without pool events end
in their start state. In a single-pass replay the second condition holds by construction; the
third and fourth are the independent checks. Result: 659,799 of 659,799 blocks, 0 missing,
0 duplicates, 0 inconsistencies.
*Proves:* the basis series and the episode runs have no holes, and block-end states match the
events.

**A3: trader + LP + protocol fee = 0.** For every swap and horizon with a markout, the absolute
residual must be below 1e-6 USD; a row with a markout but a null or NaN residual fails. Result:
2,671,386 values, largest residual 2.205524651799351e-11 USD.
*Proves:* no missing or misaligned LP or fee column at any horizon. *Does not prove:* that the
reference price is right; the identity holds by construction.

**A4: reference coverage (Ruling 6).** Per horizon, the swaps without a reference. A null is allowed
only when `t0 + h` is at or after the window end or before the first Binance trade; any other null
fails. Also reports the swaps whose 0 s reference is older than 5 s. Result: no unexpected null;
0, 0, 10, 35 and 454 nulls at 0, 12, 60, 300 and 3,600 s; 73,139 swaps with a 0 s reference older
than 5 s (covered by the `exclude_stale_over_5s` variant).
*Proves:* no swap inside the data silently lacks a reference.

**A5: label coverage (reported).** Notional share of `other_contract` (0.10897229175784204) and of
every label, and the top unlabelled transaction targets.

**A6: builder payments (reported).** Over the 110,989 top-bot transactions: 56,724 internal
transfers from a top bot to the block's fee recipient, 6 to other addresses; a share of
0.5110776743641262 of these transactions carry a coinbase payment; 0 top-bot transactions without a
single/multi-pool scope.
*Proves:* the matching works (fee-recipient addresses compare correctly, and almost all of the bots'
internal transfers in these transactions go to the fee recipient). *Does not prove:* that all
builder payments are seen (see the limitation in section 5).
