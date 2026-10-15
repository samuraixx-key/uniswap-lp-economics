# Methodology: price discovery, markouts and LP P&L (sub-projects 2 and 3)

This file defines every quantity in `results/` and gives its formula. Scope: the Uniswap V3
USDC/WETH 0.05% pool (`0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`) against Binance, window
`[2026-07-01, 2026-10-01)` UTC. Sections 1–8 cover sub-project 2 (design spec
[`docs/superpowers/specs/2026-10-13-price-discovery-markouts-design.md`](superpowers/specs/2026-10-13-price-discovery-markouts-design.md));
sections 9–17 cover sub-project 3, LP P&L and where LVR goes (design spec
[`docs/superpowers/specs/2026-10-14-lp-pnl-lvr-design.md`](superpowers/specs/2026-10-14-lp-pnl-lvr-design.md)).
Where an implementation plan amended a spec, the ruling is cited ("Ruling n"); the sub-project 3
rulings that changed a definition or a number are listed in
[Changes in sub-project 3](#changes-in-sub-project-3). Numbers quoted here come from `results/`,
except where a sentence names another source.

Notation: `f` = pool swap fee = 500 pips = 0.0005; `c` = Binance trading fee assumed for the
arbitrage (0 or 1 bp); `P_cex(t)` = reference price at time `t` (section 2); pool prices are in
USDC per WETH; 1 bp = 10⁻⁴.

Contents: [1 Data](#1-data-and-validation) · [2 Reference price](#2-reference-price-and-time-zero) ·
[3 Markouts](#3-markouts) · [4 Flow labels](#4-flow-labels) ·
[5 Costs](#5-costs-and-builder-payments) · [6 Price discovery](#6-price-discovery) ·
[7 Available arbitrage](#7-available-arbitrage) · [8 Checks](#8-checks-a1a6)

Sub-project 3: [9 Positions](#9-positions) ·
[10 Accumulators](#10-fee-and-lvr-accumulators) · [11 Measured LVR](#11-measured-lvr) ·
[12 Theoretical LVR](#12-theoretical-lvr) · [13 P&L](#13-pl-in-the-window) ·
[14 Lifetime](#14-lifetime-pl-against-holding) · [15 Where LVR goes](#15-where-lvr-goes) ·
[16 Checks](#16-checks-l1l7-and-r1r5) · [17 Limitations](#17-limitations-of-sub-project-3) ·
[Changes in sub-project 3](#changes-in-sub-project-3)

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
of the protocol's quarter (881,290.13 USD). The quarter is most of that gap. Summed from
[`results/lvr_daily.csv`](../results/lvr_daily.csv) (`fees_usd + protocol_fee_usd`), total swap
fees are 3,525,477.30 USD, short of LVR by 178,319.46 USD. By volatility tercile, total fees − LVR
is +31,703.62 (low), +54,157.72 (mid) and −264,180.80 USD (high), and LVR exceeds total fees on 41
of the 92 days (against 79 for LP fees). This matches the sub-project 2 all-swaps trader markout of
+0.25 bp at 0 s (95% interval −0.14 to 0.77, section 3): by the identity above, the counterparties'
total markout is LVR minus total fees.

## 12. Theoretical LVR

For each interval `[t, t + Δ)` of a grid of Binance reference prices over the window, `Δ` = 1 s
(primary) or 60 s (sampling sensitivity):

```
r            = ln(P_cex(t + Δ) / P_cex(t))
lvr_theory   = r² × L_dec × √P_cex(t) / 4          L_dec = L_raw × 10⁻¹²
```

`L_raw` is the active liquidity at the start of the block in force at `t`. For a full-range position
this reduces to the textbook `σ²/8 ×` pool value. Per UTC day, `RV_day = Σ r²` of the 1 s returns,
`σ_annual = √(365 × RV_day)` and `σ = √(RV_day / 86,400)` per √second.

**Fee and block-time adjustment** (Milionis, Moallemi, Roughgarden 2023, arXiv:2305.14604, Theorem 1
and Eq. 12):

```
P_trade = 1 / (1 + η),   η = √(2λ) × γ / σ,   γ = ln(1 + 0.0005),   λ = 1/12 s⁻¹
theory_arb      = theory_1s × P_trade           expected arbitrage profit
theory_arb_fees = theory_1s × (1 − P_trade)     expected fees paid by arbitrage
```

Window totals ([`results/lp_pnl.md`](../results/lp_pnl.md)): theory 3,158,845.51 USD with 1 s
returns and 4,333,659.24 USD with 1-minute returns, against measured 3,703,796.76 USD;
`theory_arb` 933,257.67 USD and `theory_arb_fees` 2,225,587.84 USD. The model assumes geometric
Brownian motion and blocks arriving as a Poisson process with rate λ, while Ethereum slots are a
fixed 12 s; the 1 s realised variance of Binance's last trade also contains order-flow noise and
stale stretches. The 1-minute total is about a third higher than the 1 s one, so the sampling
choice matters as much as the model.

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
- **Against rebalancing:** `pnl_rebal = fees − lvr_0 − gas` (and `pnl_rebal_12` with `lvr_12`).
- **Against holding:** everything the LP got out minus everything put in, all at the Binance price
  at the position's exit (its last removal, or the window end):
  `pnl_hold = V_exit + fees + Σ withdrawn − Σ deposited − gas`. Deposits and withdrawals are token
  amounts; a position open at the window start deposits, at that moment, the token amounts it held
  at the snapshot pool price. This compares the LP with holding the deposited tokens.
- **Rate:** `bp_per_day = pnl_rebal / (twv × days) × 10⁴` (and `bp_per_day_hold` with `pnl_hold`).
  `twv`, the time-weighted value, is the mean of the position's USD value at each UTC hour start in
  `[t_start, t_exit)`: its liquidity at that time, as token amounts at the pool price of the block
  in force, valued at that block's `P_cex` (Ruling 5). A position open at no hour start uses the
  value of its first in-window deposit (or of its start holdings) at that block's price. `days` is
  `(t_exit − t_start) / 86,400 s`; a `jit` position counts one 12 s slot.
- **Groups** ([`results/lp_groups.md`](../results/lp_groups.md)), by LP type, range width, holding
  time and cohort: count, Σ fees, Σ LVR, Σ gas, Σ `pnl_rebal`, Σ `pnl_hold`, the share with
  `pnl_hold > 0`, and `bp_per_day = Σ pnl_rebal / Σ (twv × days) × 10⁴`, i.e. weighted by
  value × time, with a 95% interval from a bootstrap over positions (1,000 resamples, seed 42,
  2.5th to 97.5th percentile of the same ratio).
- **Daily series** ([`results/lvr_daily.md`](../results/lvr_daily.md)): per UTC day, LP fees,
  protocol fees, measured LVR at 0 s and 12 s, the searcher part, realised variance, `σ_annual`,
  the theoretical values and the regime.

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
- LP gas is not counted in lifetime P&L.

## 15. Where LVR goes

Per block in the window, from the builder tables (Ruling 4: aggregated inside BigQuery, because the
window has about 110 M transactions):

```
R_b = Σ_tx gas_used × (effective_gas_price − base_fee)     (transactions not sent by the fee recipient)
    + Σ successful trace payments to the fee recipient
Q_b = value of the block's last transaction if it is sent by the fee recipient;
      otherwise R_b (the fee recipient is the proposer: a self-built block)
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

Trace payments cover every searcher, not only the top bots of sub-project 2. **Scope:** a
transaction is single-pool when it emits no log from an address other than our pool, USDC, WETH and
its target (`COALESCE(to_address, the contract created)`); this is counted for every transaction
touching our pool. Multi-pool transactions are reported gross only.

The chain ([`results/lvr_destination.md`](../results/lvr_destination.md), chart 12) runs: pool LVR
at 0 s (3,703,796.76 USD) → minus the other flows (−440,321.24) → LVR on searcher steps
(4,144,118.00) = LP fees (1,976,144.85) + protocol fees (658,714.87) + searcher gross
(1,509,258.29); gross = multi-pool gross (257,681.73) + single-pool gross (1,251,576.57); single-pool
gross = gas burned (9,715.89) + builder margin (654,139.41) + proposer (789,291.15) + kept
(−201,569.88). Shares are of the LVR on searcher steps: 0.4769, 0.1590, 0.0622, 0.0023, 0.1578,
0.1905 and −0.0486. This section counts every searcher step, also any with no liquidity in range,
so its keys are named apart from the accrued-only totals of section 13. No swap needed a fallback:
0 swaps without an other-logs row, 0 in a block missing from the split, 0 with null costs.

Required limitation text (also in the README and `results/lvr_destination.md`):

> The split of builder payments between builder and proposer uses each block's ratio of proposer payment to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments are identified as the block's last transaction from the fee recipient and cross-checked against relay data on a sample of blocks only.

`kept` is still an upper bound, as in section 5: payments outside the transaction (a separate
transaction in the bundle, off-chain agreements) are missed, and failed transactions are not
seen. It is negative because builder margin plus proposer payment (0.1578 + 0.1905 = 0.3483 of
the LVR on searcher steps) exceeds the single-pool gross at 0 s (1,251,576.57 / 4,144,118.00 =
0.3020). Gross is measured at the block time, so kept is a small difference of large totals.
Sub-project 2's positive kept at 12 s (`kept_12s_usd`, +59,529.77 USD) covers the top 4 bots'
single-pool transactions only, not every searcher.

## 16. Checks L1–L7 and R1–R5

Written to [`results/lp_checks.md`](../results/lp_checks.md) (and `.json`). L1–L7 are gated: `ulpe
lp` computes everything, then writes the checks and, only if all pass, the results (`summary.json`
last). R1–R5 are reported. All pass in this run.

| Check | Rule | Result |
|---|---|---|
| L1 swap reproduction | Every swap bit-exact in one of the three modes (section 10) | 534,377 swaps, 0 unreproduced; 496,936 exact input, 25,846 exact output, 11,595 to price |
| L2 fee accumulators vs chain | At each of the 500 sample blocks, `feeGrowthGlobal0/1` and the sampled ticks' `feeGrowthOutside0/1` equal the engine's exactly | 500 blocks, 18,125 values, 0 mismatches |
| L3 positions vs chain | The contract mirror's liquidity, `feeGrowthInside0/1LastX128` and `tokensOwed0/1` equal the chain's for every open pool key and NPM token at the window's last block, and the start state matches the rebuilt positions | 12,263 compared, 0 mismatches, 0 start mismatches |
| L4 fees vs Collect | For every position opened, closed and fully collected in the window (the chain owes nothing at the end), engine fees = collected − withdrawn principal, exactly in raw units. Positions that received carried owed tokens, or handed theirs on to a re-mint (section 9.2), are skipped | 3,428 positions, 0 mismatches |
| L5 start state | Σ liquidity of the positions open at the snapshot, per tick, equals the snapshot tick book (`liquidity_net` and `liquidity_gross`), and active liquidity matches | 3,837 positions, 1,557 ticks, 0 mismatches |
| L6 identities | Σ position fees ≤ pool LP fees, short by at most one raw unit per accrued step, one per window flow and two per position (Ruling 13); Σ position LVR = pool LVR and pool LVR = the markout identity (section 11), relative error ≤ 1e-9 | Pool LP fees 1,337,421,456,289 raw USDC and 618,857,678,632,566,990,117 wei; positions short by 4,870 and 5,011 (tolerance 620,992) |
| L7 history complete | The history's window `Mint`/`Burn` events equal `events.parquet`, each belongs to exactly one position, and every NPM event of our tokens matches a pool event | 21,850 liquidity events, 0 missing, 0 extra, 0 unassigned; 8 no-op zero collects |
| R1 relays | Relay-reported proposer payment vs `Q_b`, on 1,000 random window blocks | 769 found on a relay; 699 of them match within 1 wei (the same 699 within 1%) |
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
  skipped; Flashbots was skipped after about 600 blocks. 769 of the 1,000 blocks were found on a
  relay; of the 231 not found, 190 have at least one relay that was not checked (per-relay counts
  from `relays.parquet`, not in `results/`). 70 of the 769 (9.1%) differ by more than 1%, for a
  reason not established here. The match rate, 699 / 769 = 90.9%, only just clears the plan's
  threshold: below 90%, the method or a join was to be investigated before the write-up.

## 17. Limitations of sub-project 3

- **Reference = last Binance ETHUSDC trade**, as in sub-project 2; measured LVR, fees in USD and
  every P&L move with it. Sub-project 4 tests a mid price and OKX.
- **Theory** assumes geometric Brownian motion and Poisson blocks, while Ethereum slots are a
  fixed 12 s; 1 s realised variance of last trades includes order-flow noise. The 1-minute version
  is about a third higher than the 1 s one.
- **LP hedging and other holdings are not observed.** P&L against rebalancing is what an LP who
  rebalanced at Binance's price would have made; a hedged LP's real result also depends on the
  hedge's own costs.
- **LP gas** is counted only for window transactions; gas before the window and in lifetime P&L
  is not.
- **Lifetime values before the window** use ETHUSDT 1-minute closes (USDT, not USDC).
- **Who the LP is.** An NFT position's LP is its owner at close (570 window-active positions changed
  owner while open), and a vault stands for many depositors. Only four vault addresses are labelled;
  other managers stay `nft_contract` or `direct_other`.
- **Collected amounts of NFT positions** keep the NPM's requested amounts, which overstate what the
  pool paid by at most 48 raw USDC units and 44 wei per collect (2,622 collects in the history).
- **Direct keys with carried owed tokens** shift principal and fees between two positions of the
  same key; flagged positions are excluded from lifetime statistics (none among the window-active
  positions in this run), but a carry of fees only (principal fully collected) is not flagged.
- **Where LVR goes:** the limitation text of section 15; `kept` is an upper bound. The relay
  cross-check disagrees on 70 of 769 blocks (9.1%) by more than 1%, unexplained.
- **Path dependence.** P&L against holding, in the window and over a lifetime (65.7% of positions
  beat holding; 79% of those with a life of 180 days or more), depends on the price path over each
  position's life, and so on when it opened and closed.
- **Fees net of the protocol.** "Fees do not cover LVR" holds for LP fees; total swap fees fall
  short of LVR by much less (section 11).
- **Scope:** one pool and one quarter.

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
| LP gas | Gas of window mint/burn/collect transactions | A missing receipt, block price or gas field stops the run instead of costing 0 |
| Time-weighted value | Averaged over the position's blocks | Sampled at UTC hour starts (Ruling 5); a position open at no hour start is valued at its first in-window deposit, not the sum of its deposits |
| Lifetime prices | ETHUSDT 1-minute closes | A close older than 3,600 s before a deposit stops the run (a missing month file or a data gap) |
| Headline totals | Sums over steps | Fee and LVR totals sum accrued steps only; the destination counts every searcher step, so its keys are named apart (`lvr_on_searcher_swaps_usd`, …) from `lvr_0_searcher_usd`. Identical in this window (no step without liquidity) |
| Builder data (D5) | Download every window transaction and value trace (dry runs 32 GB and 288 GB) | Aggregated inside BigQuery into three tables (Ruling 4); trace payments exclude transactions sent by the fee recipient and `delegatecall`/`callcode`/`staticcall` traces; the other-logs target is `COALESCE(to_address, contract created)` and covers every pool transaction. The three queries scanned about 661 GB, against the spec's estimate of about 320 GB, mostly because of the joins that exclude the fee recipient's own transactions |
| R2 | All top-bot payments vs traces | Restricted to transactions that touch our pool, the population the trace table covers |
| Relay sample (R1) | Retries, cached | A circuit breaker skips a relay after 3 consecutive failed blocks: bloXroute max-profit timed out and was skipped, Flashbots was skipped after about 600 blocks; 769 of 1,000 blocks found, and 190 of the not-found blocks have relays that were not checked |
