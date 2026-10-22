# Methodology: who makes money on Uniswap V3

This file defines every quantity in `results/` and gives its formula. Scope: the Uniswap V3
USDC/WETH 0.05% pool (`0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`) against Binance, window
`[2026-07-01, 2026-10-01)` UTC. Sections 1–8 cover sub-project 2 (design spec
[`docs/specs/2026-10-13-price-discovery-markouts-design.md`](specs/2026-10-13-price-discovery-markouts-design.md));
sections 9–17 cover sub-project 3, LP P&L and where LVR goes (design spec
[`docs/specs/2026-10-14-lp-pnl-lvr-design.md`](specs/2026-10-14-lp-pnl-lvr-design.md)).
Where an implementation plan amended a spec, the ruling is cited ("Ruling n"); the sub-project 3
rulings that changed a definition or a number are listed in
[Changes in sub-project 3](#changes-in-sub-project-3). Sections 18–21 cover reference and timing
robustness, proposer payments, the recipient check through forwarders and the strategy
experiment, each with its own spec. Section 0 says why the main choices were made; section 22
lists every limitation. Numbers quoted here come from `results/`, except where a sentence names
another source.

Notation: `f` = pool swap fee = 500 pips = 0.0005; `c` = Binance trading fee assumed for the
arbitrage (0 or 1 bp); `P_cex(t)` = reference price at time `t` (section 2); pool prices are in
USDC per WETH; 1 bp = 10⁻⁴.

Contents: [0 Why these choices](#0-why-these-choices) · [1 Data](#1-data-and-validation) · [2 Reference price](#2-reference-price-and-time-zero) ·
[3 Markouts](#3-markouts) · [4 Flow labels](#4-flow-labels) ·
[5 Costs](#5-costs-and-builder-payments) · [6 Price discovery](#6-price-discovery) ·
[7 Available arbitrage](#7-available-arbitrage) · [8 Checks](#8-checks-a1a6)

Sub-project 3: [9 Positions](#9-positions) ·
[10 Accumulators](#10-fee-and-lvr-accumulators) · [11 Measured LVR](#11-measured-lvr) ·
[12 Theoretical LVR](#12-theoretical-lvr) · [13 P&L](#13-pl-in-the-window) ·
[14 Lifetime](#14-lifetime-pl-against-holding) · [15 Where LVR goes](#15-where-lvr-goes) ·
[16 Checks](#16-checks-l1l7-and-r1r6) · [17 Limitations](#17-limitations-of-sub-project-3) ·
[Changes in sub-project 3](#changes-in-sub-project-3)

Then: [18 Reference and timing](#18-reference-and-timing-robustness-sub-project-4) ·
[19 Proposer payments](#19-proposer-payment-detection) ·
[20 Recipient check](#20-recipient-check-through-forwarders) ·
[21 Strategy experiment](#21-strategy-experiment-phase-5) ·
[22 Limitations](#22-limitations-whole-project)

## 0. Why these choices

My short answers to "why did you…?"; each links to the section with the detail.

- **Why Binance's last ETHUSDC trade as the price?** Binance leads this pool by a block
  ([section 6](#6-price-discovery)), so it is the price an arbitrageur acts on, and ETHUSDC is the
  same pair, with no USDT/USDC rate mixed in. There is no Binance bid/ask history for 2026, so the
  last trade stands in for the mid; a trade-side mid proxy and ETHUSDT move the LP result by
  $0.14M at most ([section 2](#2-reference-price-and-time-zero),
  [section 18](#18-reference-and-timing-robustness-sub-project-4)).
- **Why read it at the block timestamp?** It is the start of the slot, the early end of when a
  block is sealed, and the bots' own decision and hedge times are not observed. So t0 is a
  convention, and I measure how much it matters: read 2 s earlier, the bots' edge is 1.80 bp instead
  of 2.86 bp, and LP fees − LVR turns positive only if prices are read more than 3 s before the
  slot ([section 3.4](#34-robustness-variants), [section 18](#18-reference-and-timing-robustness-sub-project-4)).
- **Why notional-weighted markouts?** The question is how much money changes hands: the
  weighted mean is total markout over total notional, so it adds up to the dollar totals. The
  unweighted median is reported beside it; for searchers it has the opposite sign (−0.57 bp
  against +2.86 bp) because their edge sits in the larger swaps
  ([section 3.3](#33-aggregation-and-the-day-bootstrap)).
- **Why bootstrap over days?** Resampling whole days keeps the dependence within a day
  (volatility clusters, bot activity) inside each draw. It treats days as independent of each
  other, and that is the assumption to challenge
  ([section 3.3](#33-aggregation-and-the-day-bootstrap)).
- **Why measure LPs against a rebalancing portfolio, not against holding?** LVR is the loss
  against a portfolio that rebalances at Binance's price, which isolates the adverse-selection cost
  of quoting a stale price. P&L against holding mostly measures the window's price path (−$18.2M in
  the window, most of it not LVR), so I report it but do not use it as the benchmark
  ([section 11](#11-measured-lvr), [section 13](#13-pl-in-the-window)).
- **Why 5% of active liquidity as the price-taker line?** The strategy test assumes a strategy
  takes its share of the recorded swaps without changing them. I check that assumption instead of
  modelling a large LP: 5% is the line I fixed before any result, above which a cell is flagged as
  outside it. Flagged cells are still reported, and the verdict says when it depends on them
  ([section 21.3](#213-range-strategies), [section 21.7](#217-paired-bootstrap-and-decisions)).
- **Why a margin of ±0.068 on fees ÷ LVR?** δ = (1 − r₀) / 4, a quarter of the full-range LP's
  July distance to break-even (r₀ = 0.7292), set by formula and frozen before August–September was
  computed ([section 21.1](#211-periods-and-the-freeze)).
- **Why a second pre-registered check for the proposer split?** The first test's recipient check
  failed: about half of all payments pass through one forwarding contract, which the check could
  not see through, although every payment matched the relay to the wei. Changing the check after
  seeing it fail and keeping the result would have been redefining a check until it passes, so I
  wrote the new check down, tagged it, and only then drew a fresh holdout. The first decision stays
  on file ([section 19.5](#195-why-the-recipient-check-failed-a-forwarding-contract),
  [section 20](#20-recipient-check-through-forwarders)).

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

Required limitation text (also in [REPORT.md](../REPORT.md), `results/arbitrage.md` and `results/bot_profit.md`):

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

The waterfall (figure 8) runs: available → captured (all searchers) → top-bot single-pool gross →
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

## 9. Positions

### 9.1 Data added in sub-project 3

All git-ignored under `DATA_DIR/raw`, except the labels.

| File | Source | Content |
|---|---|---|
| `history/pool_events.parquet`, `history/npm_events.parquet` | BigQuery `crypto_ethereum.logs`, one paid query from the pool's creation (2021-05-04) to the window end; dry run 2.98 TB | Every pool `Mint`/`Burn`/`Collect`, and the NonfungiblePositionManager (NPM, `0xc364…fe88`) `IncreaseLiquidity`/`DecreaseLiquidity`/`Collect`/`Transfer` logs of tokens in our pool |
| `chain_state/snapshot_fees.parquet` | RPC at the snapshot block 25,433,938 | `feeGrowthGlobal0/1X128` and every initialized tick's `feeGrowthOutside0/1X128` |
| `chain_state/sample_fees.parquet` | RPC at the 500 sample blocks of check C3 | The same values for the sampled ticks (check L2) |
| `chain_state/start_positions.parquet`, `end_positions.parquet` | RPC at the snapshot block and at the window's last block | `pool.positions(key)` and `NPM.positions(tokenId)`: liquidity, `feeGrowthInside0/1LastX128`, `tokensOwed0/1` |
| `chain_state/owner_code.parquet` | `eth_getCode` at the window's last block | Whether each LP address has contract code, and its EIP-7702 delegate if any |
| `builders/block_revenue.parquet`, `pool_tx_direct_payments.parquet`, `pool_tx_other_logs.parquet` | BigQuery `transactions`, `traces` and `logs`, aggregated inside BigQuery (Ruling 4) | Section 15 |
| `relays.parquet` | MEV-Boost relay data APIs (free) | Relay-reported proposer payments for 1,000 random window blocks (check R1) |
| `binance/ETHUSDT-1m-YYYY-MM.zip` | data.binance.vision, checksum-verified | ETHUSDT 1-minute klines from the pool's creation month to the window start (section 14) |
| `labels/lp_addresses.csv` (committed) | Etherscan, one source link per address | LP vaults (section 9.3) |

The history query runs in two stages. Stage 1 selects the pool's and the NPM's logs with the seven
event signatures into a BigQuery table that expires after 7 days; stage 2 reads that table only:
pool events as they are, and NPM events of tokens in our pool. A token is in our pool when one of
its `IncreaseLiquidity` events shares a transaction with a pool `Mint` owned by the NPM with the
same liquidity.

### 9.2 Identity

- **NFT positions.** One position per NPM `tokenId`, over its whole life. Each NPM event is
  matched to the pool event the NPM emitted just before it in the same transaction:
  `IncreaseLiquidity` to a `Mint` owned by the NPM with the same liquidity, `DecreaseLiquidity`
  to a `Burn` of the same liquidity and range, `Collect` to a `Collect` on the same range (preceded
  by a `Burn` of 0, the NPM's "poke", when the token still holds liquidity). A token whose first
  `IncreaseLiquidity` matches no `Mint` in our pool belongs to another pool and is ignored; any
  other unmatched event stops the run with its block and log index.
- **NPM collect amounts.** The NPM's `Collect` event logs the amounts it requested,
  `min(amountMax, the token's tokens owed)`. The pool pays `min(requested, the NPM key's tokens
  owed)`, and the key's owed can be lower than the sum of its tokens' owed by floor rounding. So a
  pool `Collect` matches when its amounts are at most the NPM's in both tokens. The position's flow
  keeps the NPM amounts, which is the NPM's own accounting (and what checks L3 and L4 compare).
  Over the whole history there are 2,622 such shortfalls, the largest 48 raw USDC units and 44 wei.
- **Direct positions** (minted by any address other than the NPM) are keyed as the contract keys
  them, `(owner, tick_lower, tick_upper)`. A mint on a key with zero liquidity starts a new
  position; burns and collects go to the key's latest position.
- **Zero collects on keys never minted.** `UniswapV3Pool.collect` does not check that a position
  exists and emits `Collect(0, 0)` for any key. Such events are contract no-ops: no position, no
  flow. There are 179 in the history, 8 of them in the window (check L7).
- **Carried owed tokens.** When a direct key is minted again before its earlier position collected
  all it burned, the contract keeps the old tokens owed in the same slot, and the next collect pays
  them to the new position. The earlier position is flagged `carry_out` and the later one
  `carry_in` (the test: the earlier position burned more of either token than it collected). The
  split between the two cannot be recovered before the window, where fees are not known. Check L4
  skips both (section 16) and the lifetime statistics exclude flagged positions (section 14,
  `n_excluded_carry`); the window P&L is unaffected. In this run `n_excluded_carry` is 0.
- **LP.** For an NFT position, the token's owner when the position closes (its liquidity reaches 0
  and is never increased again), or at the window end, from the NPM `Transfer` events. For a
  direct position, the key's owner. An NFT position whose owner changed while it held liquidity is
  flagged `transferred` (check R4: 570 of the 7,874 window-active positions).
- **Window-active:** liquidity > 0 at some moment in `[WINDOW_START, WINDOW_END)`. A position whose
  only window event is a collect is not window-active. 7,874 positions are window-active; 3,837 of
  them were open at the snapshot (check L5).

### 9.3 LP types, range width, holding time and cohort

- **LP type** (first match): `jit` (not open at the window start, and its first deposit and its
  exit are in the same block, ending with no liquidity); `lp_vault` (the LP is in
  `labels/lp_addresses.csv`); `nft_wallet` (NFT position whose LP has no contract code at the
  window's last block); `nft_contract` (NFT position whose LP has code); `direct_other` (every other
  direct position, whatever its owner).
- **EIP-7702.** A delegated EOA has the code `0xef0100` followed by its 20-byte delegate. It is a
  wallet controlled by a private key, so `has_code` means real contract code and a delegated EOA
  counts as a wallet. Of the 4,112 addresses read (LPs and owners of window-active positions), 287
  have contract code and 861 are delegated EOAs (counts from the `eth_getCode` fetch,
  `owner_code.parquet`; they are not in `results/`).
- **LP vault labels.** An address is labelled `lp_vault` only if Etherscan names it as an LP vault
  or active manager. Four addresses qualify: a Gamma Hypervisor, a Harvest UniVaultProxy and two
  Enzyme external positions; each row of `labels/lp_addresses.csv` has its source link. Smart
  accounts, utility contracts and unverified contracts are not labelled, so they stay
  `nft_contract` or `direct_other`.
- **Range width:** `(1.0001^(tick_upper − tick_lower) − 1) × 10⁴` bp; buckets `<50`, `50-200`,
  `200-1000`, `1000-5000`, `>=5000` bp (the last includes full range).
- **Holding time in the window:** `same_block` (the `jit` positions), `whole_window` (open at both
  ends), else by exit time minus start time: `<1h`, `1h-1d`, `1d-7d`, `>=7d`.
- **Cohort:** `pre_window` (liquidity > 0 at the window start) or `in_window`.

## 10. Fee and LVR accumulators

**Swap reproduction.** Every swap of the window is re-simulated step by step from the replayed
state, and the first of three modes that reproduces its logged amounts and final `sqrtPriceX96`
bit-exactly is kept: (1) exact input of the logged input amount, (2) exact output of the logged
output amount, (3) "to price": exact input of an unlimited amount with the logged final price as
the limit. Each step records its start and end price, liquidity, `amount_in`, `amount_out`, fee and
crossed tick. Check L1: 496,936 swaps in mode 1, 25,846 in mode 2 and 11,595 in mode 3; none
unreproduced.

**Exact accumulators** (`lp/state.py`), as `UniswapV3Pool` and `Tick` keep them, all modulo 2²⁵⁶:

```
cut              = fee // feeProtocol nibble of the input token     (0 when off; 4 in this window)
lp_fee           = fee − cut
fee_growth_in   += lp_fee × 2¹²⁸ // L                               (only when L > 0)
cross tick t:      outside_t = global − outside_t                   (before the liquidity change)
init tick t:       outside_t = global if t ≤ current tick, else 0   (Tick.update; a cleared tick is re-initialized fresh)
inside(lo, hi)   = global − below(lo) − above(hi)                   (Tick.getFeeGrowthInside)
```

`L` is the step's active liquidity. A step with `L` = 0 pays the fee (and the protocol's cut) but
grows nothing and is marked not accrued; there are 0 such steps in this window.
**Flash loans** pay LP fees too: `UniswapV3Pool.flash` adds each token's paid fee, net of the
protocol's cut, to the fee growth exactly like a swap fee. The engine records it as one step per
token paid, with the flow label `flash` and no LVR; a WETH flash fee is valued at `P_cex(t0)` of
the most recent swap.

**Float accumulators**, with the same global/outside/inside mechanics, per step:

```
fee_usd_growth  += lp_fee × (USD per raw unit of the input token at P_cex(t0)) / L
lvr_growth[h]   += lvr_step[h] / L           h ∈ {0, 12} s (section 11)
```

USDC is taken at face value. The exact accumulators start from the chain's values at the snapshot
block; the float ones start at zero there, for the global value and for every tick (Ruling 3).
Only differences between two checkpoints are ever used, and "nothing accrued on either side since
the snapshot" is a valid starting state for the outside convention.

**Contract mirror and attribution** (`lp/ledger.py`), two layers kept apart:

- The **contract mirror** holds what the chain stores, updated only by events: every pool `Mint`
  and `Burn` (including the NPM's `Burn` of 0) adds `liquidity × (inside − inside_last) // 2¹²⁸`
  to the key's `tokensOwed` and stores the new `inside_last`; a pool `Collect` reduces
  `tokensOwed`. NPM tokens mirror the NPM's own accounting on `IncreaseLiquidity`,
  `DecreaseLiquidity` and `Collect`, reading the pool key's stored fee growth, as the NPM reads
  `pool.positions(key)`, never the ticks: the pool `Burn` just before a `DecreaseLiquidity` may have
  cleared them (Ruling 14). The mirror starts from the chain's `positions()` values at the snapshot,
  read for every pool key touched after the snapshot (a new position on a previously used key
  inherits that key's stored state) and every NPM token open at the window start. Check L3 compares
  the mirror with the chain at both ends.
- The **attribution layer** holds what each position earned in the window: exact raw fees
  `liquidity × Δinside // 2¹²⁸`, checkpointed at the position's own events and at the window
  boundaries (so its floors match the contract's), and USD fees and LVR from the float
  accumulators, also checkpointed at the first event of each new UTC day (Ruling 9). A position's
  `fees` are realised plus uncollected, LP share only.

## 11. Measured LVR

Per swap step (`token0` = USDC, `token1` = WETH, decimal-adjusted, `P = P_cex(t0 + h)`):

```
lvr_step[h] = −(Δusdc + Δeth × P)
```

where `Δ` are the pool's token changes **excluding the fee**: `+amount_in` of the input token and
`−amount_out` of the output token. It is signed: positive when the trade gained against Binance
(the pool gave a better price than Binance's), negative when the pool gained. `h` = 0 s is primary
and 12 s a sensitivity; a step without a 12 s reference would contribute 0 and be counted (check
R5: 0 of 586,360 steps).

Pool LVR is the sum over accrued steps: **3,703,796.76 USD at 0 s** and 4,089,325.49 USD at 12 s.
On searcher steps it is 4,144,118.00 USD; the other flows' steps sum to −440,321.24 USD, i.e. as a
whole they lost to the pool against Binance even before the fee.
This is a net, measured quantity: it counts every flow, not only arbitrage.

**Identity with the sub-project 2 markouts.** A markout's amounts include the fee and the LVR's
exclude it, so summed over each swap's steps

```
Σ_steps lvr_step[0] = trader_markout_usd(0) + total swap fee (LP + protocol) at P_cex(t0)
```

and therefore LP fees − LVR on a swap equals its sub-project 2 LP markout at 0 s. Check L6
enforces the identity over the window: 3,703,796.7592831883 USD from the steps against
3,703,796.7592831957 USD from the markouts (relative tolerance 1e-9).

**LP fees vs total fees.** The headline `fees_minus_lvr_usd` (−1,059,609.59 USD) uses LP fees, net
of the protocol's quarter (881,290.13 USD). The quarter is most of that gap. Total swap fees
(`daily` in `summary.json`, summed from `fees_usd + protocol_fee_usd` of
[`results/lvr_daily.csv`](../results/lvr_daily.csv)) are 3,525,477.30 USD, short of LVR by
178,319.46 USD, with a 95% day-bootstrap interval of −566,463.71 to +91,433.73 (section 13). By
volatility tercile (`total_fees_minus_lvr_usd` in [`results/vol_regimes.md`](../results/vol_regimes.md)),
total fees − LVR is +31,703.62 (low), +54,157.72 (mid) and −264,180.80 USD (high), and LVR exceeds
total fees on 41 of the 92 days (against 79 for LP fees). This matches the sub-project 2 all-swaps trader markout of
+0.25 bp at 0 s (95% interval −0.14 to 0.77, section 3): by the identity above, the counterparties'
total markout is LVR minus total fees.

## 12. Theoretical LVR

For each interval `[t, t + Δ)` of a grid of Binance reference prices over the window, `Δ` = 1 s
(primary) or 60 s (sampling sensitivity):

```
r            = ln(P_cex(t + Δ) / P_cex(t))
lvr_theory   = r² × L_dec × √P_cex(t) / 4          L_dec = L_raw × 10⁻¹²
```

`L_raw` is the active liquidity in force at `t`: the end-of-block liquidity of the last block at or
before `t` (the state the next block's arbitrage trades against). For a full-range position
this reduces to the textbook `σ²/8 ×` pool value. Per UTC day, `RV_day = Σ r²` of the 1 s returns,
`σ_annual = √(365 × RV_day)` and `σ = √(RV_day / 86,400)` per √second.

**Fee and block-time adjustment** (Milionis, Moallemi, Roughgarden 2023, arXiv:2305.14604, Theorem 1
and Eq. 12):

```
P_trade = 1 / (1 + η),   η = √(2λ) × γ / σ,   γ = ln(1 + 0.0005),   λ = 1/12 s⁻¹
theory_arb      = theory_1s × P_trade           expected arbitrage profit
theory_arb_fees = theory_1s × (1 − P_trade)     expected fees paid by arbitrage
```

Window totals ([`results/lp_pnl.md`](../results/lp_pnl.md)): theory 3,155,610.48 USD with 1 s
returns and 4,325,747.96 USD with 1-minute returns, against measured 3,703,796.76 USD;
`theory_arb` 931,857.47 USD and `theory_arb_fees` 2,223,753.00 USD. The model assumes geometric
Brownian motion and blocks arriving as a Poisson process with rate λ, while Ethereum slots are a
fixed 12 s. The 1-minute total is about a third higher than the 1 s one, so the sampling choice
matters as much as the model. Order-flow noise in Binance's last trade would push the 1 s
realised variance above the 1-minute one; it comes out below, so at 1 s stale stretches (the last
trade catching up with the price over several seconds) dominate, and noise does not.

**Volatility regimes.** The 92 days are ranked by `σ_annual` (ordinal rank) and split into terciles:
rank ≤ n/3 is `low` (30 days), ≤ 2n/3 `mid` (31), else `high` (31)
([`results/vol_regimes.md`](../results/vol_regimes.md)). The regime × LP type table sums the
per-day attribution of section 10.

## 13. P&L in the window

Per window-active position, in USD ([`results/positions.csv`](../results/positions.csv)):

- `fees`, `lvr_0`, `lvr_12` from the attribution layer.
- `gas`: every window transaction that changed the position (mint, burn, collect, increase,
  decrease, poke): `receipt_gas_used × receipt_effective_gas_price / 10¹⁸ × P_cex` at its block,
  split equally across the positions it touched. A transaction without a receipt, a block without a
  price, or a null gas field stops the run rather than costing 0.
- `direct`: direct ETH payments to the block's fee recipient in those same transactions (the
  `pool_tx_direct_payments` builder table of section 15), split and priced the same way. The
  priority fee inside `gas` is one half of a builder payment and a direct payment the other, so
  both are LP costs. A transaction that also swaps in the pool may pay for the swap rather than
  for the liquidity; `jit_own_swaps` below reports such transactions.
- **Against rebalancing:** `pnl_rebal = fees − lvr_0 − gas − direct` (and `pnl_rebal_12` with
  `lvr_12`).
- **Against holding:** everything the LP got out minus everything put in, all at the Binance price
  at the position's exit (its last removal, or the window end):
  `pnl_hold = V_exit + fees + Σ withdrawn − Σ deposited − gas − direct`. Deposits and withdrawals
  are token amounts; a position open at the window start deposits, at that moment, the token amounts it held
  at the snapshot pool price. This compares the LP with holding the deposited tokens.
- **Rate:** `bp_per_day = pnl_rebal / (twv × days) × 10⁴` (and `bp_per_day_hold` with `pnl_hold`).
  `twv`, the time-weighted value, is the mean of the position's USD value at each UTC hour start in
  `[t_start, t_exit)`: its liquidity at that time, as token amounts at the pool price of the block
  in force, valued at that block's `P_cex` (Ruling 5). A position open at no hour start uses the
  value of its first in-window deposit (or of its start holdings) at that block's price. `days` is
  `(t_exit − t_start) / 86,400 s`; a `jit` position counts one 12 s slot.
- **Groups** ([`results/lp_groups.md`](../results/lp_groups.md)), by LP type, range width, holding
  time and cohort: count, Σ fees, Σ LVR, Σ gas, Σ direct, Σ `pnl_rebal`, Σ `pnl_hold`, the share
  with
  `pnl_hold > 0`, and `bp_per_day = Σ pnl_rebal / Σ (twv × days) × 10⁴`, i.e. weighted by
  value × time, with a 95% interval from a bootstrap over positions (1,000 resamples, seed 42,
  2.5th to 97.5th percentile of the same ratio).
- **JIT per swap** (spec section 6; `jit_per_swap` in `summary.json` and
  [`results/lp_pnl.md`](../results/lp_pnl.md)): a `jit` position is active for the swaps of its
  block that lie, in log order, between its first liquidity add and its last removal. The jit
  totals of fees, LVR, gas, direct payments and both P&Ls are divided by the number of such
  position-swap pairs: 844 positions, 826 of them with at least one swap, 914 pairs; +3.90 USD per
  swap against rebalancing (fees 5.20, LVR −31.66, gas 21.63, direct 11.33). The median over
  positions with a swap is +0.09 USD per swap.
- **JIT transactions that also swap** (`jit_own_swaps` in `summary.json`): the transactions of
  `jit` positions that also hold a pool swap: 265 of 1,662, with 298 swaps whose 0 s trader
  markout sums to −14,295.61 USD. The `jit` positions carry 8,711.70 USD of gas and 10,305.31 USD
  of direct payments in those transactions (of 10,353.71 USD of JIT direct payments in
  all), counted per transaction from `cost_shares`: a JIT position usually has two transactions,
  mint and burn, and only the swapping ones count. Such a payment may be for the swap, and the
  rebalancing benchmark takes the operator's own swaps as free: JIT's 3,562.64 USD against
  rebalancing becomes about −10,733 USD with the swaps' markout added. The swaps lie outside the
  JIT positions' spans (all but 6, worth −0.01 USD, come before the first add or after the last
  removal), so they trade against other LPs and do not overlap the JIT positions' LVR.
- **Daily series** ([`results/lvr_daily.md`](../results/lvr_daily.md)): per UTC day, LP fees,
  protocol fees, measured LVR at 0 s and 12 s, the searcher part (LVR, LP fees and protocol fees on
  searcher swaps), realised variance, `σ_annual`, the theoretical values and the regime.
- **Day bootstrap** (spec section 6: the pool-level daily series keep sub-project 2's day
  bootstrap; `daily` in `summary.json`): the window total of a daily series is resampled by drawing
  92 days with replacement, 1,000 times (seed 42), and the interval is the 2.5th to 97.5th
  percentile of the resampled totals. LP fees − LVR: −1,059,609.59 USD, 95% interval
  −1,533,757.96 to −712,591.77. Total fees − LVR: −178,319.46 USD, interval −566,463.71 to
  +91,433.73. As in section 3.3, days are treated as independent.

Headline totals (`lp_fees_usd`, `lvr_0_usd`, `lvr_12_usd`, and the accrued-only
`lvr_0_searcher_usd`, `lp_fees_searcher_usd`) sum accrued steps only: a step with no liquidity in
range paid no LP. Section 15 counts every searcher step; in this window the two coincide, as no
step lacked liquidity.

## 14. Lifetime P&L against holding

For every window-active position, over its whole history
([`results/lifetime.md`](../results/lifetime.md)):

```
pnl_hold_life = (Σ collected + owed and accrued at the window end + V_end − Σ deposited) at P_exit
return_life   = pnl_hold_life / Σ deposits, each valued at its own time
beat_hold     = pnl_hold_life > 0
```

- Deposits are pool `Mint` amounts (direct) or NPM `IncreaseLiquidity` amounts (NFT); collected
  amounts are pool `Collect` (direct) or NPM `Collect` (NFT) and include the withdrawn principal,
  so withdrawals are not added again. Fees are implicit: collected minus withdrawn principal, plus
  what is still owed or accrued at the window end (from the engine).
- `P_exit` is the window-end price for an open position, else `P_cex` at the block of its last
  removal. Deposits inside the window are valued at `P_cex` of their block; deposits before it at
  the last ETHUSDT 1-minute close known at the deposit time (a bar's close is stamped at the bar's
  end). A close older than 3,600 s, a deposit block without a price, or a closed position without
  a removal stops the run.
- Positions flagged `carry_in` or `carry_out` (section 9.2) are left out of every share and median;
  `n_excluded_carry` reports how many (0 here). Lifetime holding buckets: `<1d`, `1-7d`,
  `7-30d`, `30-180d`, `>=180d`.
- The position's window costs (`gas + direct`, section 13) are subtracted from `pnl_hold_life`, so
  the window and lifetime results charge the same costs; gas and builder payments before the
  window are not observed and not charged.

## 15. Where LVR goes

Per block in the window, from the builder tables (Ruling 4: aggregated inside BigQuery, because the
window has about 110 M transactions):

```
R_b = Σ_tx gas_used × (effective_gas_price − base_fee)     (transactions not sent by the fee recipient)
    + Σ successful trace payments to the fee recipient
Q_b = value of the block's last transaction if it is sent by the fee recipient;
      otherwise R_b (taken to be self-built: the fee recipient is the proposer; primary method)
proposer_share_b = Q_b / R_b      (0 when R_b = 0; above 1 when the builder subsidises)
```

A **trace payment** is a successful trace with value > 0 to the block's fee recipient, inside a
transaction the fee recipient did not send (its own transactions, e.g. unwrapping WETH, are
excluded), and not a `delegatecall`, `callcode` or `staticcall` (those move no value of their own).

Per searcher swap (sub-project 2 label), with the transaction's costs split across its swaps in
our pool by notional, in USD at `P_cex(t0)`:

```
gross          = trader_markout_usd(0)
gas_burned     = gas_used × base_fee
builder_paid   = gas_used × (effective_gas_price − base_fee) + trace payments to the fee recipient in the tx
proposer       = builder_paid × proposer_share_b
builder_margin = builder_paid − proposer
kept           = gross − gas_burned − builder_paid
```

Trace payments cover every searcher, not only the top bots of sub-project 2. A transaction
that both swaps and moves JIT liquidity (section 13) has its gas and payments counted here as the
searcher's cost and in section 13 as the LP's cost; the two analyses are never added together. **Scope:** a
transaction is single-pool when it emits no log from an address other than our pool, USDC, WETH and
its target (`COALESCE(to_address, the contract created)`); this is counted for every transaction
touching our pool. Multi-pool transactions are reported gross only.

The chain ([`results/lvr_destination.md`](../results/lvr_destination.md), the hero figure) runs: pool LVR
at 0 s (3,703,796.76 USD) → minus the other flows (−440,321.24) → LVR on searcher steps
(4,144,118.00) = LP fees (1,976,144.85) + protocol fees (658,714.87) + searcher gross
(1,509,258.29); gross = multi-pool gross (257,681.73) + single-pool gross (1,251,576.57); single-pool
gross = gas burned (9,715.89) + builder margin (848,648.09) + proposer (594,782.47) + kept
(−201,569.88). Shares are of the LVR on searcher steps: 0.4769, 0.1590, 0.0622, 0.0023, 0.2048,
0.1435 and −0.0486 (builder margin and proposer from the measured payments of sections 19 and
20; until section 20 the published split was the two-sided pair below). This section counts every searcher step, also any with no liquidity in range,
so its keys are named apart from the accrued-only totals of section 13. No swap needed a fallback:
0 swaps without an other-logs row, 0 in a block missing from the split, 0 with null costs.

**The self-built fallback, and a sensitivity.** 105,361 of the 659,799 window blocks (16.0%)
have transactions but no last transaction from the fee recipient, so the primary method gives
their proposer all of the builder revenue (the 175 blocks with no transactions were counted here
before proposer-payment detection; they carry no revenue). Section 19 measures what these blocks
paid: nearly all of their builder dollars sit in blocks that pay from a separate payout address,
and a blind relay holdout matches those payments to the wei. That measured split was not adopted
at first, because its pre-registered recipient check failed (section 19.5); a second
pre-registered test with a recipient check that follows forwarding contracts passed (section 20),
and the measured split is now the published one. The primary method and the sensitivity below
are kept as the record of what was published before; `summary.json` no longer carries
`sensitivity_self_built`.

These blocks carry 297,357.38 USD (0.2060) of the 1,443,430.55 USD of single-pool builder
payments (11,432 swaps), and 0.3767 of the primary proposer total. The sensitivity
(`sensitivity_self_built` in `summary.json`, second table of `results/lvr_destination.md`) gives
them the paid blocks' proposer share instead of 1:

```
self_built_proposer_share = Σ Q_b / Σ R_b over paid blocks = 0.4915
```

Revenue-weighted, because what is split is a sum of dollars: each wei of builder revenue counts
once, and a block with almost no revenue, whose per-block share can be very large when the
builder subsidises the proposer, cannot pull it. The median per-block share of the paid blocks
(0.6240) is reported beside it. Result, with shares of LVR on searcher steps:

| | primary (self-built share 1) | sensitivity (share 0.4915) |
|---|---|---|
| proposer, USD | 789,291.15 (0.1905) | 638,079.53 (0.1540) |
| builder margin, USD | 654,139.41 (0.1578) | 805,351.02 (0.1943) |

Their sum (0.3483), gas, kept and every other figure are the same under both. Builder margin
exceeds the proposer payment for any share below 0.77 in these blocks, so the ordering does not
depend on choosing the weighted ratio over the median. Both are superseded by the measured
split (proposer 594,782.47, 0.1435; builder margin 848,648.09, 0.2048), which lies outside the
pair: most of these blocks paid their proposer from a payout address, and paid less than either
method assumed.

Required limitation text (also in [REPORT.md](../REPORT.md) and `results/lvr_destination.md`):

> The split of builder payments between builder and proposer uses each block's ratio of proposer payment to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments are identified as the block's last transaction, sent by the fee recipient or by a payout address learned from chain data, and tested on a blind stratified relay sample; blocks where neither applies give the proposer the whole builder revenue.

`kept` is still an upper bound, as in section 5: payments outside the transaction (a separate
transaction in the bundle, off-chain agreements) are missed, and failed transactions are not
seen. It is negative because builder margin plus proposer payment (0.2048 + 0.1435 = 0.3483 of
the LVR on searcher steps) exceeds the single-pool gross at 0 s (1,251,576.57 / 4,144,118.00 =
0.3020). Gross is measured at the block time, so kept is a small difference of large totals.
Sub-project 2's positive kept at 12 s (`kept_12s_usd`, +59,529.77 USD) covers the top 4 bots'
single-pool transactions only, not every searcher.

## 16. Checks L1–L7 and R1–R6

Written to [`results/lp_checks.md`](../results/lp_checks.md) (and `.json`). L1–L7 are gated: `ulpe
lp` computes everything, then writes the checks and, only if all pass, the results (`summary.json`
last). R1–R6 are reported (R6: section 18.5), never gate, and show "reported" in the Result column. All of L1–L7
pass in this run.

| Check | Rule | Result |
|---|---|---|
| L1 swap reproduction | Every swap bit-exact in one of the three modes (section 10), and none that the LP engine's own replay fails to reproduce | 534,377 swaps, 0 unreproduced; 496,936 exact input, 25,846 exact output, 11,595 to price; 0 unmatched in the engine |
| L2 fee accumulators vs chain | At each of the 500 sample blocks, `feeGrowthGlobal0/1` and the sampled ticks' `feeGrowthOutside0/1` equal the engine's exactly | 500 blocks, 18,125 values, 0 mismatches |
| L3 positions vs chain | The contract mirror's liquidity, `feeGrowthInside0/1LastX128` and `tokensOwed0/1` equal the chain's for every open pool key and NPM token at the window's last block, and the start state matches the rebuilt positions | 12,263 compared, 0 mismatches, 0 start mismatches |
| L4 fees vs Collect | For every position opened, closed and fully collected in the window (the chain owes nothing at the end), engine fees = collected − withdrawn principal, exactly in raw units. Positions that received carried owed tokens, or handed theirs on to a re-mint (section 9.2), are skipped | 3,428 positions, 0 mismatches |
| L5 start state | Σ liquidity of the positions open at the snapshot, per tick, equals the snapshot tick book (`liquidity_net` and `liquidity_gross`), and active liquidity matches | 3,837 positions, 1,557 ticks, 0 mismatches |
| L6 identities | Σ position fees ≤ pool LP fees, short by at most one raw unit per accrued step, one per window flow and two per position (Ruling 13); Σ position LVR = pool LVR and pool LVR = the markout identity (section 11), relative error ≤ 1e-9 | Pool LP fees 1,337,421,456,289 raw USDC and 618,857,678,632,566,990,117 wei; positions short by 4,870 and 5,011 (tolerance 620,992) |
| L7 history complete | The history's window `Mint`/`Burn` events equal `events.parquet`, each belongs to exactly one position, and every NPM event of our tokens matches a pool event | 21,850 liquidity events, 0 missing, 0 extra, 0 unassigned; 8 no-op zero collects |
| R1 relays | Relay-reported proposer payment vs `Q_b` of the payout rule (section 19), on 1,000 random window blocks, by block class and round (seen / retry / holdout), with R1b (recipient) and R1c (proposer is fee recipient) | 771 of the 1,000 found on a relay; 767 match within 1 wei (the same 767 within 1%): all 699 paid and 66 payout-address blocks found, 2 found in the retry, none of the 4 unexplained. Not found: 188 with bloXroute unchecked, 41 answered by every relay. Holdout and R1b, R1c: section 19 |
| R2 traces vs Alchemy | Top-bot payments to the fee recipient from sub-project 2's Alchemy transfers vs the trace payments, on transactions touching our pool | 56,724 of 56,724 equal |
| R3 LP-type coverage | Positions and fees by LP type | Table in `lp_checks.md`; 111 `lp_vault` positions |
| R4 transferred | NFT positions whose owner changed while open | 570 of 7,874 |
| R5 12 s reference | Steps without a 12 s reference | 0 of 586,360 |

What they prove and what they do not:

- L1–L3 and L5 are exact-integer comparisons with the chain: the engine reproduces every swap, the
  fee accumulators at 500 blocks, and every open position's stored state at both ends. The USD
  values and LVR rest on the float accumulators, which only L6 checks, as identities.
- L4 checks fees against what LPs actually collected, but only for positions that opened, closed
  and collected inside the window.
- **R1 sample.** The relay fetch has a circuit breaker: a relay that fails (time-out, server error
  or invalid JSON after retries) on 3 consecutive blocks is skipped for the rest of the run, and
  later blocks count as not checked on it. bloXroute max-profit timed out from the start and was
  skipped; Flashbots was skipped after about 600 blocks. The 190 blocks left unchecked were
  retried (section 19.3): Flashbots answered (2 found), bloXroute max-profit failed on all 188
  others. Under the old self-built fallback the 1,000 blocks gave 699 matches of 769 found, all 70
  mismatches being "self-built" blocks; under the payout rule of section 19 they give 767 of 771,
  and the 4 left are the unexplained class.

## 16a. Figures

`ulpe figures` renders every figure from `results/` only (`summary.json`, the results CSVs and
`results/figure_data/`), in light SVG with text as outlines, so a re-render with unchanged
inputs changes no file. The style (palette, Inter font, title block) is in `viz/style.py`.

| Figure | Inputs |
|---|---|
| Hero: where the LVR on searcher swaps went | `summary.json` `lp.destination` |
| 1 What is LVR (schematic) | none |
| 2 A stale-pool episode (and GIF) | `figure_data/episode_blocks.csv`, `episode_cex.csv` |
| 3 The pool follows Binance | `figure_data/basis_hist.csv`, `episodes.csv`, `summary.json` `lead_lag` |
| 4 Markouts by flow | `markouts.csv` |
| 5 LVR and fees against volatility | `lvr_daily.csv` |
| 6 Cumulative fees vs LVR | `lvr_daily.csv`, `summary.json` `lp.daily` |
| 7 Measured vs theoretical LVR | `lvr_daily.csv` |
| 8 Do bots keep the edge | `summary.json` `arbitrage`, `bot_profit.csv` |
| 9 Every position | `positions.csv` |
| 10 P&L by group | `lp_groups.csv` |
| 11 One JIT block | `figure_data/jit_block.csv`, `positions.csv` |
| 12 Lifetime vs holding | `summary.json` `lp.lifetime*` |
| 13 Reference and timing | `reference_robustness.csv`, `summary.json` `lp.robustness`, `lp.protocol_fees_usd` |

**Episode selection (figure 2).** The day with the largest measured LVR (0 s; the earliest on
ties); within it, the 20-block stretch with the largest absolute Binance log move; the figure shows
32 blocks starting 4 blocks before that stretch (fewer at the day's edges).

**JIT block selection (figure 11).** Among JIT positions whose own transactions (mint and burn) also
hold a pool swap before the first liquidity add and one after the last removal, the one with the
largest P&L vs rebalancing (then the lowest block, then the id). Without such a position, the most
profitable JIT position, and the figure says so. In the block shown, the operator's first swap
moves the pool from $1,794.90 to $1,759.93; its liquidity then buys the next trader's ETH at that
low price, a "negative LVR" of $2,093.08. The position made $1,125.36 against rebalancing, but the
operator's own two swaps lost $1,088.90 against Binance at 0 s: all in, the operator came out
$36.47 ahead ([`results/figure_data/jit_block.csv`](../results/figure_data/jit_block.csv)).

**"$10k" framing (figure 10).** P&L per $10,000 of time-weighted position value per 30 days =
`bp_per_day × 30`, since `bp_per_day` is P&L per 10⁴ of value per day.

**Line of best fit (figure 5).** Ordinary least squares of log USD per day on log annualised
volatility, over days with positive LVR and fees; the break-even is where the two fits cross.

## 17. Limitations of sub-project 3

Merged into [section 22](#22-limitations-whole-project), with every other sub-project's limitations.

## Changes in sub-project 3

Sub-project 3 made the Binance reference deterministic. Before, when several trades shared a
microsecond, the reference was an arbitrary one of them. Now the latest aggregated trade ID wins
(section 2). It also added two checks to A2: the last block lies within one 12 s slot of the window
end, and the block series covers the last event. Re-running sub-project 2 with these changes
(`ulpe build`, `validate`, `analyze`; C1–C6 and A1–A6 all PASS) changed no reported number:

| metric | before | after |
|---|---|---|
| any number in `results/` | — | unchanged (largest relative difference 6e-15, from floating-point summation order) |

So the old sort already left same-microsecond trades in trade-ID order in this data. The new rule
makes that guaranteed rather than incidental.

Sub-project 3 also replaced the approximate protocol fee with the exact one (section 3). Before,
`protocol_fee_usd` was `ceil(amount_in × 500 / 10⁶) × 1/4`, with WETH valued at the pre-swap pool
price. Now every swap is re-simulated step by step: 534,377 swaps, all reproduced bit-exactly
(check L1: 496,936 as exact input, 25,846 as exact output, 11,595 to the logged price). The
protocol takes `fee // 4` of each step's fee, and WETH is valued at `P_cex(t0)`. The protocol fee
only enters the LP markout, which no published table reports, so again no reported number changed.

| metric | before | after |
|---|---|---|
| swaps whose raw fee differs from the approximation | — | 26,338 (by a few raw units each) |
| total protocol fee, USD | 881,671.39 | 881,290.13 |
| A3 largest residual, USD | 2.2e-11 | 7.0e-12 |
| any number in `results/` | — | unchanged (largest relative difference 7e-15) |

### Where the code departs from the sub-project 3 spec

Reviewed rulings during implementation changed several definitions in the design spec. Sections
9–17 describe the code; this list says what changed and why.

| Topic | Spec | Code, and why |
|---|---|---|
| Flash loans | Fee growth from swap steps only | `UniswapV3Pool.flash` also grows fee growth, so flash fees accrue to LPs: one step per token paid, labelled `flash`, no LVR (section 10). Without it, L2 fails |
| Zero collects | Every pool event belongs to a position | A `Collect(0, 0)` on a key never minted is a contract no-op: no position, no flow; 179 in the history, 8 in the window (section 9.2) |
| NPM collect match | Exact amounts | The NPM logs requested amounts and the pool pays `min(requested, key owed)`; the pool `Collect` may be lower. Matched when ≤ in both tokens; flows keep the NPM amounts; 2,622 shortfalls, at most 48 raw USDC units and 44 wei |
| Direct key re-minted before its owed is collected | Not covered | The old owed stays in the slot and goes to the new position. `carry_in`/`carry_out` flags; L4 skips positions that handed on or received owed tokens; flagged positions are excluded from lifetime statistics and counted in `n_excluded_carry` |
| NPM token accounting | Fee growth inside from the ticks | Read from the pool key's stored fee growth, as the NPM does (Ruling 14) |
| Start state | Keys and tokens open at the window start | Every pool key touched after the snapshot is read at the snapshot (a new position on an old key inherits its stored owed); NPM tokens open at the window start |
| L6 fee tolerance | 1 raw unit per step | Also one per window flow and two per position, never above the pool's (Ruling 13) |
| Owner code | `has_code` from `eth_getCode` | EIP-7702 delegated EOAs (code `0xef0100` + delegate) are wallets, not contracts: 861 of the 4,112 addresses read are delegated, 287 are real contracts |
| LP vault labels | Web-verified vaults and managers | Only addresses Etherscan names as vaults or managers: 4 addresses, with sources in `labels/lp_addresses.csv` |
| LP gas | Gas of window mint/burn/collect transactions | A missing receipt, block price or gas field stops the run instead of costing 0. Direct payments to the fee recipient in the same transactions are charged too (`direct`), as the other half of a builder payment (pre-merge review) |
| Lifetime costs | Not specified | The position's window gas and direct payments are subtracted, so window and lifetime results charge the same costs (pre-merge review) |
| Time-weighted value | Averaged over the position's blocks | Sampled at UTC hour starts (Ruling 5); a position open at no hour start is valued at its first in-window deposit, not the sum of its deposits |
| Lifetime prices | ETHUSDT 1-minute closes | A close older than 3,600 s before a deposit stops the run (a missing month file or a data gap) |
| Headline totals | Sums over steps | Fee and LVR totals sum accrued steps only; the destination counts every searcher step, so its keys are named apart (`lvr_on_searcher_swaps_usd`, …) from `lvr_0_searcher_usd`. Identical in this window (no step without liquidity) |
| Builder data (D5) | Download every window transaction and value trace (dry runs 32 GB and 288 GB) | Aggregated inside BigQuery into three tables (Ruling 4); trace payments exclude transactions sent by the fee recipient and `delegatecall`/`callcode`/`staticcall` traces; the other-logs target is `COALESCE(to_address, contract created)` and covers every pool transaction. The three queries scanned about 661 GB, against the spec's estimate of about 320 GB, mostly because of the joins that exclude the fee recipient's own transactions. Proposer-payment detection added a fourth table, each block's last transaction (`to_address`, gas; 15.2 GB, section 19) |
| R2 | All top-bot payments vs traces | Restricted to transactions that touch our pool, the population the trace table covers |
| Theoretical LVR liquidity | Active liquidity `L_b` at block start | The end-of-block liquidity of the last block at or before the interval start: the state in force during the interval, which the next block's arbitrage trades against. Theory with 1 s returns moved from 3,158,845.51 to 3,155,610.48 USD |
| JIT per swap | "Reported in USD per swap" (no definition) | P&L over the swaps between the position's first add and last removal in its block, per position-swap pair (section 13) |
| Builder tables | `fetch-builders` (no flag) | A billable run needs `--confirm-cost`, like `fetch-history`; a dry run is free and needs none |
| Relay sample (R1) | Retries, cached | A circuit breaker skips a relay after 3 consecutive failed blocks: bloXroute max-profit timed out and was skipped, Flashbots was skipped after about 600 blocks; 769 of 1,000 blocks found, and 190 of the not-found blocks have relays that were not checked |

## 18. Reference and timing robustness (sub-project 4)

Every headline number reads the Binance ETHUSDC last trade at or before the block timestamp
(t0, the slot start). This section re-measures LP fees − LVR under other references and other
read times. Code: `lp/robustness.py`, `align.trade_side_table`, `data/block_timing.py`.

### 18.1 References

| name | price at time t |
|---|---|
| `binance_last_trade` (primary) | last ETHUSDC trade at or before t |
| `binance_trade_side_mid` | mean of the latest buyer-initiated trade (`is_buyer_maker = false`, printed at the ask) and the latest seller-initiated trade (printed at the bid) at or before t |
| `binance_ethusdt_1s_close` | latest ETHUSDT 1 s close at or before t (quoted in USDT) |

Binance publishes no best bid/ask history for 2026 (spot or futures `bookTicker`), so the mid is
a proxy built from the trade files already downloaded. A quiet side goes stale, so the two sides
can cross; `results/reference_robustness_proxy.md` reports the crossed share, spread quantiles
and the mean distance of the last trade from the proxy mid at swap times.

### 18.2 Offsets and the shift method

Prices are read at t0 + d for d from −5 s to +4 s in 0.5 s steps. Through the L6 identity, per
swap, LP fees − LVR = `amount_usdc + amount_eth × P − protocol fee(P)`, where only the WETH
amounts move with P (the WETH protocol fee; USDC fees do not). Each cell is

    headline + Σ_swaps [X(P_cell) − X(P_primary at 0 s)]

summed by UTC day, so the primary 0 s cell is the headline by construction, flash-loan fees
included. LP fees in a cell move only through WETH-denominated LP fees. A swap with no price in a
cell (offset past the window end, or the proxy before both sides have traded) gets a zero shift
and is counted in `n_unpriced`.

### 18.3 Paired day bootstrap

One matrix of resampled days (1,000 draws, seed 42, drawn as `theory.day_bootstrap_sum` draws)
serves every cell. Each cell gets the 95% interval of its total, which for the primary 0 s cell
is the headline's interval, and the 95% interval of its shift from the primary 0 s cell, computed
on the same draws. The paired interval is what says whether a shift between references is
larger than day-to-day noise.

### 18.4 Winning-bid times

For the 1,000 relay-sample blocks (seed 42; a second batch, seed 43, if fewer than 150 are
timed), Titan, Flashbots and Aestus are asked in that order for the delivered payload
(`proposer_payload_delivered`: winning block hash and slot) and their received bids
(`builder_blocks_received`). The winning-bid time is the earliest received bid with the delivered
hash, minus slot start (`1,606,824,023 + 12 × slot` seconds). Only these three relays publish
July 2026 bids; ultrasound, the largest relay, keeps none for the window. A block can be delivered
by several relays, so a sampled block is timed whenever one of the three delivered it, including
many blocks ultrasound also delivered. What is missing is the blocks none of the three delivered
(or that one delivered but no longer lists, counted as `n_delivered_not_timed`): blocks that went
only through relays without bid history, or were found on no relay. They could be sealed at
different times. Quantiles are in
`results/block_timing.md`; the 10th–90th percentile band is drawn on figure 13. The headline
stays at 0 s.

### 18.5 Check R6 (reported)

The identity summed at the headline prices plus the flash loans' LP fees equals the headline
fees − LVR, and re-reading the primary reference at 0 s moves nothing (`primary_reprice_usd`),
both within the L6 relative tolerance.

## 19. Proposer-payment detection

Design: [`docs/specs/2026-10-21-proposer-payments-design.md`](specs/2026-10-21-proposer-payments-design.md).
Its pre-registered parts (the rule, the holdout, the bar and the stopping rule) were committed
before any holdout relay call; the commit is tagged `holdout-preregistered`.

### 19.1 Data

A fourth builder table, `last_tx.parquet` (15.2 GB): each block's last transaction's `to_address`
and `receipt_gas_used`, 659,624 rows (every block with transactions). The `input` column was left
out (194.8 GB). `fetch-payout-code` reads, over RPC, the code of each payout recipient paid with
more than 21,000 gas, at the first and last block it was paid in: 161 reads, 93 recipients.

### 19.2 Block classes

Each window block gets one class, in this order, from chain data only:

1. **empty**: no transactions. `R_b = Q_b = 0`.
2. **paid**: the last transaction is sent by the fee recipient F. `Q_b` = its value.
3. **payout**: the last transaction is sent by a payout address of F, has value > 0, and does not
   go back to F. `Q_b` = its value. A sender S ≠ F is a payout address of F if S sent the last
   transaction in at least 50 of F's blocks, with value > 0 in at least 99% of them.
4. **proposer is fee recipient**: F has no block in class 2 or 3 anywhere in the window.
   `Q_b = R_b`.
5. **unexplained**: everything else. `Q_b = R_b`.

| Class | Blocks | Share of blocks | Single-pool builder USD | Share |
|---|---|---|---|---|
| empty | 175 | 0.03% | 0.00 | 0% |
| paid | 554,263 | 84.00% | 1,146,073.18 | 79.40% |
| payout | 44,297 | 6.71% | 296,703.85 | 20.56% |
| proposer is fee recipient | 39,310 | 5.96% | 20.03 | 0.001% |
| unexplained | 21,754 | 3.30% | 633.49 | 0.044% |

At thresholds of 20 and 100 blocks instead of 50 the payout class has 44,640 and 44,233 blocks
(`class_counts_by_n` in `summary.json`). No payment from a payout address goes back to its fee
recipient (0 top-ups). Payout recipients by type, from the code reads (a payment of exactly
21,000 gas is a plain wallet without a read; code `0xef0100…` is an EIP-7702 delegated wallet,
counted as a wallet, not a contract; no recipient's two reads differ):

| Recipient | Payments | ETH paid | Single-pool builder USD |
|---|---|---|---|
| wallet | 9,490 | 176.52 | 59,269.43 |
| EIP-7702 wallet | 6 | 0.06 | 0.00 |
| contract | 34,801 | 677.73 | 237,434.42 |

**A known flaw of class 4, not fixed after the fact.** Two fee recipients that never pay from
themselves have a small qualifying payout pair: Lido's execution-layer rewards vault `0x388c…`
(160 payout blocks) and `0x7e2a…` (64). Because they then have a class-3 block, their other
16,967 blocks fall to unexplained instead of class 4. That is why the unexplained class has
21,754 blocks where the exploration, which keyed class 4 on paid blocks only, had 4,787 (the
same 4,787 are here). The dollars barely differ ($633.49 against about $630): these blocks carry
almost no builder payments. The rule was pre-registered, so it was not changed after the fact;
the fix was pre-registered with the second holdout instead and is in force from section 20 on
(class 4 then has 56,501 blocks and unexplained 4,787).

### 19.3 Relay rounds

`relays.parquet` gains a `round` column:

- **seen**: the original 1,000 blocks (seed 42), looked at while the rule was chosen. In 66 of the
  70 old mismatches the payment was the last transaction from a payout address, so this part is
  not blind.
- **retry**: the 190 blocks some relay never answered, asked again with a slower pace and a
  longer time-out. Flashbots answered (2 found); bloXroute max-profit failed on the other 188, in
  both retry passes. All 27 unexplained blocks in this round wait on bloXroute alone, so whether
  the unexplained blocks are bloXroute-built stays open.
- **holdout**: a fresh sample drawn after the rule was fixed (seed 44, the old sample left out),
  300 blocks from class 3 and 300 from classes 2, 4 and 5 together, written to
  `data/raw/relay_holdout.parquet` before its first relay call. 525 of the 600 were found; the 75
  not found all wait on bloXroute max-profit.

### 19.4 Checks and the result

R1 compares the relay's payment with `Q_b` of the payout rule; R1b compares the last
transaction's `to_address` with the relay's `proposer_fee_recipient`; R1c lists class-4 blocks a
relay delivered for a proposer other than the fee recipient.

| Round | Class | Found | Within 1 wei | Recipient matches |
|---|---|---|---|---|
| seen | paid | 699 | 699 | 377 |
| seen | payout | 66 | 66 | 33 |
| seen | unexplained | 4 | 0 | – |
| retry | paid | 2 | 2 | 1 |
| holdout | paid | 232 | 232 | 129 |
| holdout | payout | 289 | 289 | 132 |
| holdout | unexplained | 4 | 0 | – |

No class-4 block in any round was found on a relay (15 seen, 52 retry, 16 holdout sampled), so R1c
lists nothing: consistent with locally built blocks, as class 4 assumes.

**Pre-registered decision.** One split only if, among found holdout blocks in class 3, at least
95% match the relay within 1 wei and at least 95% pay the relay's `proposer_fee_recipient`
(a block without a relay recipient counts as a failure). Stopping rule: the holdout is fetched,
retried once, and the first `ulpe lp` after every holdout block has a row freezes the decision in
`data/raw/holdout_decision.json`; later runs publish the frozen decision and report any recomputed
one beside it. The frozen file:

```
n_found_payout        289
share_within_1_wei    1.0
share_within_1pct     1.0
share_recipient_match 0.4567   (132 / 289)
one_split             false
frozen                2026-10-22, after 600 of 600 holdout blocks had a row
```

So the published split stayed the two-sided pair of section 15, until the second holdout of
section 20 (`holdout_decision` in `summary.json` keeps this first decision; the file above is
never rewritten).

### 19.5 Why the recipient check failed: a forwarding contract

615 of the 616 recipient failures across all rounds (paid and payout classes) are payments into one
contract, `0xfeeeeee44046c3f61a8cc081e0918ef0de0a7ffc` (code `0x5f3580…`, about 29,000 gas per
payment), which passes the ETH on. R1b reads only the last transaction's `to_address`, so it
cannot see where the money ends up. The contract receives the last transaction in 291,274 of the
598,560 paid and payout-class blocks (48.7%), and it fails the primary method's own blocks the
same way: in the seen sample 377 of 699 paid blocks pass R1b, though all 699 match the relay's
payment to the wei. The bar therefore failed on the recipient check, not on the payments: every
found holdout block of the rule matches the relay's value exactly.

### 19.6 The rule's own split, not adopted

The payout rule's split was fixed with the rule before the run, so it is reported beside the
published pair, labelled as measured payments that were not adopted because the pre-registered
recipient check failed (`rule_split` in `summary.json`; last section of
`results/lvr_destination.md`):

| | primary | sensitivity | measured payments; not adopted |
|---|---|---|---|
| proposer, USD | 789,291.15 (0.1905) | 638,079.53 (0.1540) | 594,782.47 (0.1435) |
| builder margin, USD | 654,139.41 (0.1578) | 805,351.02 (0.1943) | 848,648.09 (0.2048) |

Redefining R1b now and flipping the decision would be post hoc. A recipient check that follows
internal transfers through forwarders, with its bar written down before a fresh holdout (seed 45),
was run next (section 20); it passed, and this split, with the class fix, is now the published
one.

### 19.7 What was dropped

The 261 GB trace query planned to find payments outside the last transaction: after the payout
rule, $633.49 (0.044%) of single-pool builder dollars is unexplained, too little to move the split.

## 20. Recipient check through forwarders

Design: [`docs/specs/2026-10-21-forwarder-recipient-check-design.md`](specs/2026-10-21-forwarder-recipient-check-design.md).
Sections 3 to 6 of it (the class fix, the check, the holdout, the bar and the stopping rule) were
committed and tagged `forwarder-preregistered` before the seed-45 holdout was drawn; the code was
reviewed against them before the draw. No new check was computed on the seed-44 holdout.

### 20.1 The class fix

A payout address S of fee recipient F now also needs F to send the last transaction in at least
one of its own blocks. Two fee recipients never do: Lido's execution-layer rewards vault `0x388c…`
and `0x7e2a…`; their "payout addresses" sent about 0.006 ETH (0.01 ETH) with 21,000 gas to a
different wallet almost every time, withdrawals that happened to end the block. Their 224 class-3
blocks and 16,967 other blocks move to class 4:

| Class | Blocks | Share of blocks | Single-pool builder USD | Share |
|---|---|---|---|---|
| empty | 175 | 0.03% | 0.00 | 0% |
| paid | 554,263 | 84.00% | 1,146,073.18 | 79.40% |
| payout | 44,073 | 6.68% | 296,703.85 | 20.56% |
| proposer is fee recipient | 56,501 | 8.56% | 23.42 | 0.002% |
| unexplained | 4,787 | 0.73% | 630.11 | 0.044% |

At thresholds of 20 and 100 blocks the payout class has 44,115 and 44,073 blocks. The moved
blocks carry no single-pool builder dollars as payout blocks, so the payout rule's split is the
same as in section 19.6. The six EIP-7702 payments of section 19.2 were among the moved blocks;
no payout recipient is an EIP-7702 wallet now. None of the 45 earlier relay rows of the two fee
recipients was found on a relay, so no earlier found-block count changes.

### 20.2 The check, R1d

For a block in class 2 or 3 with last transaction `h`, recipient `a0` and value `v`, the payment
path starts at `a0` and follows, at most 3 times, the single internal transfer sent by the current
address in `h` with value ≥ `v`; it stops when there is not exactly one, or on a repeat. R1d
passes if the relay's `proposer_fee_recipient` is on the path. The forwarder `0xfeeeeee…7ffc` is
20 bytes of code (`0x5f358060e01c4218600f5760401cff5b5f5ffd00`): if the first 4 calldata bytes
equal the block timestamp it self-destructs to the address in calldata bytes 4–23, which since
Cancun only sends its balance there. Paths come from free RPC (`eth_getBlockByNumber` and
`alchemy_getAssetTransfers`, which reports that transfer), for the seed-45 blocks only
(`ulpe fetch-paths`, `data/raw/holdout2_paths.parquet`): 580 paths, 331 with one hop and 249 with
none. Every block's last transaction from the RPC matched the chain tables.

### 20.3 The second holdout and the result

Seed 45, every block already in `relays.parquet` left out, 300 blocks of class 3 and 300 of
classes 2, 4 and 5 (fixed classes), written to `data/raw/relay_holdout_2.parquet` before its
first relay call; relay rows `round = "holdout2"`. A copy of the relay file was taken before the
draw, and every later write of the file is refused if a row of an earlier round would change or
be added. bloXroute max-profit failed on 78 blocks in the fetch and again in the one retry; 522
of the 600 were found.

| Stratum | Class | Found | Within 1 wei | R1b | R1d |
|---|---|---|---|---|---|
| payout | payout | 290 | 290 | 117 | 290 |
| rest | paid | 232 | 232 | 108 | 232 |
| rest | proposer is fee recipient | 0 (20 sampled) | – | – | – |

No class-4 block was found on a relay (R1c lists nothing), and the rest stratum drew no
unexplained block. The frozen decision, `data/raw/holdout_decision_2.json`:

```
n_found_payout        290
share_within_1_wei    1.0
share_within_1pct     1.0
share_recipient_match 1.0      (R1d, 290 / 290)
one_split             true
frozen                2026-10-22, after 600 of 600 holdout-2 blocks had a relay row and every
                      paid/payout block a path
```

So `ulpe lp` publishes one split (`proposer_split: "one"`, `published_decision: "holdout2"` in
`summary.json`): proposer 594,782.47 USD (0.1435 of LVR on searcher steps), builder margin
848,648.09 USD (0.2048). The first decision stays in `holdout_decision`, unchanged.

## 21. Strategy experiment (Phase 5)

Design: [`docs/specs/2026-10-21-strategy-experiment-design.md`](specs/2026-10-21-strategy-experiment-design.md).
Code: `strategy/` (every pre-registered value in `strategy/params.py`), `data/futures.py`.
Results: `results/strategy_{checks,ranges,fees,hedge,test}.md` (CSVs alongside),
`summary.json["strategy"]`, `results/strategy_freeze.json`. Every number is a counterfactual
that ignores how other traders would react to a different range, fee or hedge.

### 21.1 Periods and the freeze

July = `[2026-07-01, 2026-08-01)` (31 days) fixes the choices; the report period
`[2026-08-01, 2026-10-01)` (61 days) gives every reported number. `ulpe strategy` runs twice.
With no freeze file it computes July only and writes `results/strategy_freeze.json` (refusing if
the file exists), with the git commit and a hash of every input file: data, processed LP tables
and the futures files. That file was committed as `f565e41` and tagged `strategy-preregistered`
before the second run. The second run takes every July value from the file, stops with a message
naming it if the file cannot be read, lacks a key or was frozen on other inputs, and never
rewrites it. Frozen values:

| value | frozen | from |
|---|---|---|
| r₀, full range's fees ÷ LVR in July | 0.7292 | 21.3 |
| δ = (1 − r₀) / 4 | 0.0677 | 21.7 |
| `min_profit_gas` | 137,345 | median gas used by the distinct transactions of July's replaced swaps (21.4) |
| LP gas, mint / burn + collect | 408,316 / 208,475 gas | July medians (21.3, departure 1) |
| LP priority fee | 251,225,452 wei (0.25 gwei) | July median of those transactions' effective gas price − base fee |
| calibration (S3) | failed | 21.6 |
| best strategy | `band_5000bp`, −0.82 bp/day in July | the re-centring cell with the highest July return at $1M |

A one-day probe of S3 on 2026-07-01 (LVR ratio 1.38) was seen while the code was built. It is
July data, inside the calibration period, and nothing pre-registered was changed in response:
the 1 bp CEX fee, the minimum-profit rule and the ±15% tolerance stayed as fixed in the spec.

### 21.2 A price-taker position's share of a swap step

A strategy holds liquidity ℓ in `[tick_lower, tick_upper)` over a span of `(block, log)` order
and does not change the swaps. Each recorded step (`swap_steps.parquet`: pool liquidity L, start
and end sqrt prices, `tick_start`, `fee_usd`, `lvr_0`) is attributed by one of four cases, with
`[a, b] = [min, max]` of the step's sqrt prices and `[p_lo, p_hi]` the range's:

1. **Flat step** (a = b: a flash, or a step that does not move the price): in range iff
   `tick_lower ≤ tick_start < tick_upper`, as fee growth counts it; it then takes
   `fee_usd × ℓ / L` (a flash has no LVR). A flash with the price exactly on the lower tick is in
   range, on the upper tick out.
2. **Fully inside** (`p_lo ≤ a` and `b ≤ p_hi`): `fee_usd × ℓ / L` and `lvr_0 × ℓ / L`.
3. **Disjoint** (`b ≤ p_lo` or `p_hi ≤ a`): nothing.
4. **Partial**: the part between `max(a, p_lo)` and `min(b, p_hi)`. Per unit of liquidity
   between sqrt prices x < y (as `sqrtPriceX96 / 2^96`), the V3 delta formulas give
   `USDC = (y − x) / (x y) / 10^6` and `WETH = (y − x) / 10^18`, with `y − x` taken in integers.
   The fee share is the part's input-token amount over the whole step's (USDC for a
   `zero_for_one` step, else WETH); LVR is `ℓ × (WETH × P0 − USDC)` for `zero_for_one` and
   `ℓ × (USDC − WETH × P0)` otherwise, at the step's 0 s reference P0 (section 11's sign).

Range bounds wider than Int128 are clamped above every step price, which leaves every comparison
the same. The replay itself is not touched, so L1–L7 stay valid.

**Check S1 (gated).** Every window-active position's own range and liquidity stretches, scored
this way over its span, reproduce the engine's `fee_usd` and `lvr_0` per position and on the
window totals within a relative `1e-9 × max(1, |engine|)`: 7,874 positions, largest error
9.4e-10 (LVR) and 5.9e-10 (fees), 0 failures. The margin is thin. Real positions' bounds are
initialized ticks, so recorded steps never straddle them: S1 checks cases 1 to 3 only. Case 4
is checked by a unit test that inserts a tiny real position into a swap's path and compares the
split swap with the formula (`test_partial_step_matches_a_split_swap`).

### 21.3 Range strategies

- **Ranges.** ±w ticks (one tick ≈ 1 bp) around the block-start tick c, rounded outward to the
  10-tick spacing: `[⌊(c − w)/10⌋ × 10, ⌈(c + w)/10⌉ × 10]`, w ∈ {10, 25, 50, 100, 250, 500,
  1,000, 2,500, 5,000}; full range is ±887,270.
- **Rules**, decided on each block-start tick: *static* never re-centres; *out of range*
  re-centres when `tick < tick_lower` or `tick ≥ tick_upper`; *band* when |tick − c| > w / 2;
  *daily* at the first block of a new UTC day. A new range holds from the block start, before the
  block's simulated arbitrage and events (departure 5). 9 widths × 4 rules plus full range; the
  27 re-centring cells at $1M are the tested ones, the static cells descriptive.
- **Capital and value.** $1M (and $100k) buys the first range at the period's first block
  start, valued at the pool price and the 0 s reference. At a re-centring the old range's value at
  that block start moves into the new range: `ℓ_new = ℓ_old × V_old / V_new`, both per unit of
  liquidity at that state. Collected fees stay as cash.
- **Costs per re-centring.** Gas `(208,475 + 408,316) × (base fee + 0.25 gwei) × P_ref` and a
  5 bp taker fee (1 and 10 bp as sensitivities) on `|ΔWETH| × P_ref`, the trade that restores the
  new range's token ratio at Binance's 0 s price. The entry mint and the period-end exit are free
  for every strategy (departure 4).
- **Return.** `bp/day = Σ(fees − LVR − gas − trade) / Σ_days TWV × 10⁴`, where a day's TWV is
  the mean of the position's hourly values at the pool price in force and Binance's price
  (section 13's time-weighted value). fees ÷ LVR = Σ fees / Σ LVR (LP fees after the protocol's
  cut, LVR at 0 s). At $100k fees, LVR, trade costs and value scale by 0.1 and gas does not, so
  fees ÷ LVR is the same at both sizes.
- **Peak share.** The largest ℓ / (L + ℓ) over the attributed steps; above 5% flags the cell
  as outside the price-taker assumption (flagged cells are still counted). In-range share: the
  share of the period's block starts whose tick is inside the range in force.

### 21.4 The counterfactual pool

A copy of the snapshot tick book is carried through every window block (from the snapshot, so a
report-period number sits on a pool carried through July) and never reset to the real state:

1. the fee rule sets the block's fee from the pool price at block start (the oracle rule also
   reads Binance);
2. the simulated arbitrage: `arb_to_price` at that fee with a 1 bp CEX fee against Binance's last
   trade at the block timestamp (t0 + 1 s as a sensitivity); it trades only if its profit
   exceeds `base fee × 137,345 gas × P_ref`. The step-recording swap repeats that call's own
   band-edge limit (departure 2). Its LVR is valued at the 0 s reference in both runs;
3. the block's events in log order: mints and burns as observed; the replaced swaps skipped;
   every other swap re-executed in its own L1 mode at the block's fee (exact input: the logged
   input; exact output: the logged output; to price: an unlimited input stopped at the logged
   final price); a flash loan pays `⌊paid × fee / 500⌋` on each observed amount (departure 3).

**Replaced flow:** exactly the single-pool searcher swaps, `flow_label = searcher` with
`other_logs = 0` (99,890 swaps; 33,507 in July). A to-price swap whose limit the
counterfactual price has already reached or passed executes nothing (V3 reverts it), as does a
logged swap with no input; both leave the book unchanged and are counted, never raised
(`cfpool_counts` in `summary.json`). At 5 bp over the window: 405,879 kept swaps re-executed as
exact input, 25,681 as exact output, 2,394 to price, 533 to-price swaps skipped, 0 without input,
0 unreproduced; 99,997 arbitrage trades, 15,992 gaps whose profit did not pay the gas.

Fees and LVR per step use the engine's accumulators, split by source: the full-range position's
per-liquidity fees and LVR from arbitrage steps and from kept flow (flash loans in kept).
**Arbitrage-side fees ÷ LVR** = Σ fee_arb / Σ LVR_arb (LP fees after the protocol's cut);
**whole-pool fees ÷ LVR** adds the kept side to both. The real pool's arbitrage side is read from
the replaced swaps' recorded steps.

**Check S2 (gated).** At 5 bp with nothing replaced the book must reproduce the real pool
exactly: `sqrtPriceX96`, tick and liquidity after every block equal `blocks_state.end_*`, every
step's liquidity, amounts, fees and crossed tick (flash rows included) equal `swap_steps.parquet`,
and every swap's protocol fee equals `aligned.protocol_fee_raw`. 659,799 blocks, 586,360 steps, 534,377
swaps, 0 mismatches.

### 21.5 Fee rules

| rule | fee for a block | grid |
|---|---|---|
| fixed | f | 1, 2.5, 5 (baseline), 7.5, 10, 15, 20, 30, 50, 100 bp |
| volatility | clamp(k × √EWMA(r²), 1 bp, 100 bp); r = the pool's block-to-block log return, EWMA decay 0.5^(1/h) per block, started at 0 | k ∈ {1, 2, 4}, h ∈ {25, 150, 900} blocks (about 5 min, 30 min, 3 h) |
| move | clamp(5 bp + k × \|r of the previous block\|, 1 bp, 100 bp) | k ∈ {0.5, 1, 2, 4} |
| oracle (upper bound) | clamp(max(5 bp, \|ln(P_pool / P_ref)\| at block start), 1 bp, 100 bp) | none |

Each rule is reported with its average charged fee (mean over blocks). Every grid point is
reported; none is selected on July. The fixed levels run at the 0 s and +1 s references, the
dynamic rules at 0 s.

### 21.6 Check S3: calibration (July, reported)

The 5 bp model with the replaced swaps replaced, over July, against the measured values of the
same 33,507 July swaps: the simulated arbitrage's LVR at 0 s against their measured LVR, and its
fees before the protocol's cut against theirs. Pass: both within ±15%.

| | model | measured | ratio | ratio at +1 s |
|---|---|---|---|---|
| LVR, USD | 1,509,517.58 | 1,094,192.81 | 1.3796 | 1.3285 |
| fees, USD | 787,459.32 | 746,409.12 | 1.0550 | 1.0731 |

Failed on LVR, so every fee result is labelled model-only and the fee test is "not tested
(calibration failed)". A plausible reason, not tested: the simulated arbitrage closes the whole
gap to the fee band at every block start, while real searchers captured 0.83 of the available
arbitrage (`captured_over_available`, section 7).

### 21.7 Paired bootstrap and decisions

One matrix of 1,000 draws of the 61 report days (seed 42, drawn as `theory.day_bootstrap_sum`
draws) serves every cell. Every per-day frame is joined onto the full day grid with zeros, so
draws stay paired. In a draw, a ratio is Σ numerator / Σ denominator over the drawn days; it is
undefined when the summed LVR is ≤ 0. Δ = cell − full range (range part) or rule − the 5 bp model
at the same reference (fee part), per draw; the 95% interval is the 2.5–97.5 percentiles of the
defined draws.

- **Range part** (the 27 re-centring cells at $1M, against δ = 0.0677). *Inside*: at most 2.5%
  of draws undefined, and the interval with undefined draws placed at +∞ (`inverted_cdf`
  percentiles) within [−δ, +δ]. *Above*: the defined draws' lower bound > +δ. **Holds** if every
  cell is inside, **fails** if any is above, **inconclusive** otherwise. The verdict is recomputed
  on the unflagged cells alone; if it differs, it "depends on flagged cells". Result:
  inconclusive, and it depends on the 24 flagged cells (the three unflagged, ±5,000 bp, are
  inside; no cell is above). The point estimates above +δ are daily re-centred ranges of ±10 to
  ±50 bp (+0.088 to +0.111). Such a range is out of range most of the time (±10 bp re-centred
  daily is in range at 18% of block starts), so it misses in-range LVR when the price trends away
  during the day; that reading is an interpretation, not tested.
- **Fee part**, per fixed level f > 5 bp on the arbitrage side: holds if the lower bound > +δ,
  fails if the upper bound < +δ, inconclusive otherwise; the summary is the lowest level where it
  holds, or "fails". Levels below 5 bp are not tested, and with calibration failed no level is:
  every level reads "not tested (calibration failed)". The protocol cut and the oracle fee never
  count.

### 21.8 Break-even and the protocol cut

- **X**: the lowest fee where the whole-pool fees ÷ LVR reaches 1, linear between the fixed
  levels: 8.5967 bp.
- **Break-even volume loss** per rule: `x(f) = (R(f) − R(5 bp)) / (fees_kept(f) − LVR_kept(f))`,
  R = fees − LVR per unit of full-range liquidity, the share of kept flow the pool could lose
  before the full-range LP is no better off than at 5 bp. Shortcut: removed flow's fees and LVR
  scale linearly and the price path does not change. Undefined when the denominator is ≤ 0.
  **Y** = x interpolated linearly at X on the fixed levels: 0.4256.
- **bp/day of a fee rule**: R(f) × ℓ of the $1M full-range position / that position's TWV in the
  real pool.
- **Protocol cut** (arithmetic, real pool, full range): LP fees at cut c = measured LP fees ×
  (1 − c) / (1 − 1/4), for c ∈ {0, 1/10, 1/4}; fees ÷ LVR 1.0067, 0.9061 and 0.7550.

### 21.9 Hedge

For full range and the best July strategy at $1M: a short of the position's WETH on the Binance
USDⓈ-M ETHUSDC perpetual. On the perpetual's minute grid the position's WETH `e` and value come
from the block-start state in force at each minute's close; the hedge `h` (ETH short) is reset
to `e` at the first minute and then: *never* (h = 0 throughout: unhedged), *daily* at each new UTC
day, *hourly* at each new hour, *drift* when `|e − h| × close > 10% × value`. Per minute: hedge
P&L `−h_prev × Δclose`, trade cost `|Δh| × close × taker fee` (5 bp; 1 and 10 bp); each funding
row pays `h × close × rate` on the hedge held during its minute (a positive rate pays the short).
The perp–spot basis is in the hedge P&L by construction. Daily P&L = Δ position value + fees −
gas − re-centring trades + hedge P&L + funding − hedge trades; the **rebalancing benchmark** is
fees − LVR − gas − re-centring trades with no hedge. Reported per rule: bp/day on the TWV, and the
mean and standard deviation of daily USD P&L per $1M. The hedge changes the spread, not
fees − LVR: the benchmark is the free continuous hedge.

### 21.10 Departures from the spec

1. **LP gas medians are July medians, frozen** (spec 5.3 says window medians). A cost input that
   feeds the July best-strategy choice must not read August–September data; `min_profit_gas` is
   treated the same way.
2. **The arbitrage's step-recording swap repeats `arb_to_price`'s own call** (its band-edge
   limit), not an exact-input swap with no limit: V3 rounds the last step differently without a
   target price. An assert that both give the same output proves it is the same swap.
3. **Flash loans at a counterfactual fee pay `⌊paid × fee / 500⌋`.** V3 rounds flash fees up, so
   this can be one raw unit low per token per flash at fees other than 5 bp (exact at 5 bp, where
   S2 checks it; 57 flashes in the window).
4. **Entry and exit are free for every strategy;** only re-centrings pay gas and the taker fee
   (spec 5.3: "per re-centring"). Every strategy, full range included, would pay the same one
   mint and one exit, so no difference against full range changes.
5. **A re-centring segment starts at the block start**, before the block's simulated arbitrage
   and events.
6. **The fee runs use 4 worker processes by default** (about 1.35 GB of memory each), not one per
   core.
7. **The report files were regenerated once, after the freeze, to make re-runs byte-identical.**
   The first report run (`54ef24c`) summed floats per day with polars' parallel `group_by`, whose
   result changes in the last bits from run to run: a re-run differed by up to 3e-11 (on a value
   of about $10,000) with every flag and verdict the same. The daily sums now run on rows sorted
   by day, and every committed strategy report file comes from one run of that code; two
   consecutive runs are byte-identical apart from `generated_utc`. Against the first run, values
   moved by at most 2.9e-11 and no flag, verdict or frozen value changed. The freeze
   (`f565e41`) was not touched. The same fix (`io.ordered_group_by`, guarded by a test because polars does not
   promise the behaviour) covers the four sums in `ulpe analyze` and `ulpe lp` whose output varied
   between runs: label coverage, check R3, the markout day bootstrap and `lp_blocks.parquet`'s row
   order. Their results moved by at most 2e-15 relative, and every freeze-hashed input stayed
   byte-identical.

## 22. Limitations (whole project)

### Price discovery and markouts (sub-project 2)

> Builder payments are detected only as direct ETH transfers from the bot contract to the block's fee recipient within the same transaction. Payments routed elsewhere (another contract, a separate transaction in the bundle, off-chain agreements) are missed, so the reported net profit is an **upper bound** on what the bots keep. Binance-side trading fees, inventory and hedging costs are not observed.

- **Reference = last Binance trade.** There is no order-book data for the window, so no mid price,
  and Binance is the only reference venue. 73,139 swaps have a 0 s reference older than 5 s; the
  robustness variant without them changes little.
- **t0 = block timestamp** (whole seconds, the start of the 12-second slot), while Binance trades
  carry sub-second timestamps and the bots' decision and hedge times are not observed. Short-horizon
  markouts depend on this choice (the searchers' 0 s edge is 1.80 bp with t0 − 2 s). For LP fees
  − LVR, [section 18](#18-reference-and-timing-robustness-sub-project-4) measures how far this goes.
- **Available arbitrage ignores gas, Binance fees beyond the 1 bp sensitivity, and Binance depth.**
  It assumes the arbitrage is the first trade at the block-start state, and a gap that stays open is
  counted again at each block start, so it is not what one arbitrageur could have taken.
- **Labels are a curated list plus heuristics.** `searcher` is a structural pattern (the pool's
  caller is the transaction's target), not a verified identity, and 0.11 of notional stays
  `other_contract`; the two largest unlabelled addresses are unverified contracts with no public
  name tag.
- **Failed bot transactions are not counted.** A reverted transaction, or one that exits without
  trading, emits no Swap log in the pool, so its gas never enters the cost side. This is a further
  reason the bots' net profit is an upper bound.
- **Multi-pool bot transactions get no cost breakdown:** their costs also pay for trades in other
  pools, so they are reported gross only.
- **Builder income** is income of the block's fee recipient, usually the builder; what the builder
  passes on to the proposer is not measured here (sub-project 3 splits it for searcher swaps, see
  [section 15](#15-where-lvr-goes)).
- **Statistics:** the bootstrap resamples UTC days and treats them as independent; for a thin group
  the interval is conditional on at least one active day and can be narrow.
- **Scope:** one pool and one quarter; nothing here is tested on other pools or periods.

### LP P&L and where LVR goes (sub-project 3)

> The split of builder payments between builder and proposer uses each block's ratio of proposer payment to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments are identified as the block's last transaction, sent by the fee recipient or by a payout address learned from chain data, and tested on a blind stratified relay sample; blocks where neither applies give the proposer the whole builder revenue.

- **Reference price.** Measured LVR, fees in USD and every P&L use Binance's last ETHUSDC trade, as
  above. [section 18](#18-reference-and-timing-robustness-sub-project-4) re-measures it against a
  trade-side mid proxy, ETHUSDT and other read times.
- **Theory** assumes geometric Brownian motion and blocks arriving as a Poisson process, while
  Ethereum slots are a fixed 12 s. The 1-minute version gives about a third more LVR than the
  1-second one. Order-flow noise in last trades would push 1-second realised variance above the
  1-minute one; it comes out below, so at 1 s stale stretches of the last trade (the price
  catching up over several seconds) dominate, and noise does not.
- **LP hedging and other holdings are not observed.** P&L against rebalancing is what an LP who
  could rebalance for free at Binance's last trade would have made; a hedged LP's real result also
  depends on the hedge's own costs.
- **LP gas and builder payments** are counted only for window transactions, in the window and
  the lifetime results alike; costs before the window are not observed. A JIT transaction that also
  swaps may pay the builder for the swap, and the rebalancing benchmark takes the LP's own swaps as
  free.
- **Lifetime values before the window** use ETHUSDT 1-minute closes (quoted in USDT).
- **Who the LP is.** An NFT position's LP is its owner at close (570 window-active positions
  changed owner while open), and a vault stands for many depositors. Only four vault addresses are
  labelled (those Etherscan names as vaults); other managers stay `nft_contract` or
  `direct_other`. EIP-7702 delegated wallets count as wallets.
- **Small accounting edges, reported:** NFT collects keep the amounts the position manager
  requested, which can exceed what the pool paid by up to 48 raw USDC units or 44 wei (2,622
  collects in the pool's history); a direct position re-minted before its owed tokens were collected
  hands them to the next position, and such positions are left out of the lifetime statistics (none
  among the window-active positions), but a carry of fees only (principal fully collected) is not
  flagged.
- **Where LVR goes:** "kept" is an upper bound (builder payments outside the transaction and
  failed transactions are missed). A transaction that both swaps and moves JIT liquidity has its
  gas and builder payments counted twice, as the searcher's cost here and as the LP's cost in the
  P&L tables: at most $19,017 in this window (the 265 such transactions).
  The two analyses are never added together. The proposer/builder split (proposers 14.4%, builders 20.5% of searcher LVR) comes
  from measured payments that passed a pre-registered relay test on the second attempt; the
  first attempt's failed recipient check stays published beside it (sections 19 and
  20). Blocks left unexplained ($630.11 of builder dollars, 0.044%) give the proposer the whole
  builder revenue. The sum (34.8%) does not depend on the split. The relay sample found 771 of
  1,000 blocks; bloXroute's max-profit relay, down throughout, left 188 of them and 75 and 78
  blocks of the two holdouts without an answer.
- **Path dependence.** P&L against holding, in the window and over a lifetime (53.5% of positions
  beat holding; 78% of those with a life of 180 days or more), depends on the price path over each
  position's life, and so on when it opened and closed.
- **Fees net of the protocol.** "Fees do not cover LVR" holds for LP fees; total swap fees fall
  short of LVR by much less ([section 11](#11-measured-lvr)).
- **Statistics:** the P&L intervals bootstrap positions and treat them as independent, though many
  positions share an LP.

### Reference and timing robustness (sub-project 4)

- **The mid price is a proxy.** There is no Binance bid/ask history for the window; the
  trade-side proxy is crossed at 18% of swap times. A true mid needs another venue's order book
  (OKX publishes one, 2.9 GB for ETH-USDC), which would mix venue and mid effects.
- **Timing covers the blocks three relays delivered.** Winning-bid times come from Titan,
  Aestus and Flashbots, the relays that keep bid history for the window: 561 of 1,000 sampled
  blocks, many also delivered through ultrasound. The 439 blocks none of the three delivered are
  missing. The received
  time is when the final block reached the relay, not when each searcher read a price.
- **The headline stays at the block timestamp.** Sub-projects 2 and 3 are not re-run at the
  measured time; the robustness table re-prices LP fees − LVR only, through the L6 identity.

### Strategy experiment (Phase 5)

- **Out of sample for the parameters, not for the analyst.** Every parameter was fixed on July and
  frozen before August–September was computed, but the window's aggregate results
  (sub-projects 2–4) were known when the hypothesis was written.
- **Price-takers.** A strategy position takes its share of the recorded swaps without changing
  them. 24 of the 27 tested cells are flagged because at their peak they hold more than 5% of the
  active liquidity (up to 84%); a position that large would change the swaps it trades against.
  The flag is in the table, and the verdict depends on the flagged cells; at $100k, where only
  12 are flagged, it is still inconclusive.
- **No routing model; fixed volume.** Where flow would go at a higher fee (the 0.3% pool, other
  venues) is not modelled. Kept flow is re-executed at its logged size at every fee; the
  break-even share assumes removed flow takes its fees and LVR with it in proportion and leaves
  the price path unchanged.
- **The fee model failed calibration**, so every fee number is model-only ([section 21.6](#216-check-s3-calibration-july-reported)). The
  simulated arbitrage always trades first in the block and closes the whole gap to the fee band;
  real arbitrage sometimes trades after other swaps, and takes less.
- **Swap modes.** Kept swaps are re-executed in the mode check L1 found first (exact input, then
  exact output, then to price). A swap that was really exact output but reproduces as exact input
  at 5 bp is re-executed as exact input; at 5 bp the two cannot be told apart.
- **What is replaced.** "Searcher" is a contract that receives the transaction and calls the
  pool, not proven CEX-DEX arbitrage. 135 of the replaced swaps look like sandwich legs (0.34% of
  the replaced notional, −$712 gross at 0 s). Multi-pool searcher swaps are kept, though some of
  them are CEX-DEX arbitrage routed through other pools.
- **Hedge.** The ETHUSDC perpetual's 1-minute closes and funding files, with a 5 bp taker fee
  (1 and 10 bp as sensitivities); no depth, slippage or margin cost. Entry and exit of a strategy
  are free; only re-centrings pay gas and the taker fee, the same for every strategy.
- **Statistics:** 61 days, bootstrapped as independent days; with 27 cells, requiring every one
  inside ±δ is conservative, the right direction for a claim that something does not matter.
