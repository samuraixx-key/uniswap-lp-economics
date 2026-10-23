# Costs, price discovery and arbitrage

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
full breakdown ([`results/bot_profit.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/bot_profit.md), per bot and TOTAL):

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
[`results/arbitrage.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/arbitrage.md), and `kept_over_top_bot_gross_12s` against the
12 s markout) is `kept / top-bot single-pool gross`: numerator and denominator cover the same
transactions. The spec's `kept / captured` would divide the top bots' single-pool result by all
searchers' 0 s markouts, mixing two populations, so it is not reported.

Required limitation text (also in [the report](../../report/3-auction.md), `results/arbitrage.md` and `results/bot_profit.md`):

> Builder payments are detected only as direct ETH transfers from the bot contract to the block's fee recipient within the same transaction. Payments routed elsewhere (another contract, a separate transaction in the bundle, off-chain agreements) are missed, so the reported net profit is an **upper bound** on what the bots keep. Binance-side trading fees, inventory and hedging costs are not observed.

How to read `kept`. Gross is the 0 s markout: the swap valued at Binance's last trade at the block
timestamp. That is the edge measurable at block time, not the bots' realised hedge. `kept` is a
small difference of large totals, so its sign depends on the horizon: with the same costs, `kept`
is −$0.19M at the 0 s markout and +$0.06M at 12 s (builder income 115% vs 95% of gross; gross
$1.22M vs $1.47M; `kept_usd` and `kept_12s_usd` in
[`results/arbitrage.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/arbitrage.md)). A negative `kept` therefore does not show that
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

[`results/basis.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/basis.md): the mean and the 1, 5, 25, 50, 75, 95 and 99%
quantiles of `basis_bp` and `|basis_bp|`, and the share of blocks with `|basis_bp| > 5`. 5 bp is
the fee band: inside it, an arbitrage at the block-start price loses money before gas (section 7).

### 6.3 Gap episodes and closers

- An episode is a maximal run of consecutive blocks with `|basis_bp| > k`, for `k` = 5 bp (primary)
  and 10 bp. Runs are taken over consecutive rows of the block series, which check A2 shows has no
  missing block.
- Per episode ([`results/episodes.csv`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/episodes.csv)): start and end block, number of
  blocks, `duration_s` = time from the first to the last block's timestamp plus the interval from
  the last block to the next one (a one-block episode lasts one block interval, usually 12 s),
  peak `|basis_bp|`, and `gap_weight = Σ |basis_bp| × block seconds`.
- **Closer.** Let `e` be the episode's last block; block `e+1` starts inside the band.
  - A flow label, if at least one swap in `e` reduced `|ln(P_pool / P_cex(t_e))|` from its
    pre-swap to its post-swap price: the closer is the label of the swap that reduced it most. A
    swap that overshoots through `P_cex` counts only if the absolute log gap still shrinks.
  - `cex`, if no swap in `e` reduced the gap: Binance moved back toward the pool.
  - `open`, if `e` is the window's last block.
- Outputs ([`results/episodes.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/episodes.md)): per closer, the count and share of
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
[`results/leadlag.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/leadlag.md).

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

Outputs ([`results/arbitrage.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/arbitrage.md)): `available_usd` (`c` = 0) and
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

Written to [`results/analysis_checks.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/analysis_checks.md) (and `.json`) before any
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
2,671,386 values, largest residual 6.991740519879386e-12 USD.
*Proves:* no missing or misaligned LP or fee column at any horizon. *Does not prove:* that the
reference price is right; the identity holds by construction.

**A4: reference coverage (Ruling 6).** Per horizon, the swaps without a reference. A null is allowed
only when `t0 + h` is at or after the window end or before the first Binance trade; any other null
fails. A 0 s reference older than 600 s also fails: a hole in the Binance data would otherwise
leave the swaps in it a valid but stale price (the longest gap between two trades is 169 s).
Also reports the swaps whose 0 s reference is older than 5 s. Result: no unexpected null;
0, 0, 10, 35 and 454 nulls at 0, 12, 60, 300 and 3,600 s; oldest 0 s reference 117.8 s; 73,139
swaps with a 0 s reference older than 5 s (covered by the `exclude_stale_over_5s` variant).
*Proves:* no swap inside the data lacks a reference or has one from across a data gap.

**A5: label coverage (reported).** Notional share of `other_contract` (0.10897229175784207) and of
every label, and the top unlabelled transaction targets.

**A6: builder payments (reported).** Over the 110,989 top-bot transactions: 56,724 internal
transfers from a top bot to the block's fee recipient, 6 to other addresses; a share of
0.5110776743641262 of these transactions carry a coinbase payment; 0 top-bot transactions without a
single/multi-pool scope.
*Proves:* the matching works (fee-recipient addresses compare correctly, and almost all of the bots'
internal transfers in these transactions go to the fee recipient). *Does not prove:* that all
builder payments are seen (see the limitation in section 5).
