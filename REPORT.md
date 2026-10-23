# Who makes money on Uniswap V3: the full report

Every one of the 534,377 swaps ($7.05B notional) in the Uniswap V3 USDC/WETH 0.05% pool on
Ethereum from 2026-07-01 to 2026-10-01, measured against Binance. The question is a market-making
one: who has edge against the pool, who pays for it, and where the money ends up.

**In trading terms:** LP = passive market maker · LVR (loss-versus-rebalancing) = the
adverse-selection cost of quoting stale prices · searchers = arbitrage bots · builder/proposer
payments = what bots pay to get their trades into the block.

Contents: [1 Where is the price set?](#1-where-is-the-price-set) ·
[2 Who has edge against the pool?](#2-who-has-edge-against-the-pool) ·
[3 The arbitrage auction](#3-the-arbitrage-auction) ·
[4 The passive market maker's P&L](#4-the-passive-market-makers-pl) ·
[5 Is it the reference price?](#5-is-it-the-reference-price) ·
[6 Can an LP do better?](#6-can-an-lp-do-better) · [Data](#data) · [Reproduce](#reproduce) ·
[Further reading](#further-reading)

Why each main choice was made (reference price, t0, weighting, bootstrap, benchmark, thresholds):
[methodology section 0](docs/methodology.md#0-why-these-choices). Every limitation:
[methodology section 22](docs/methodology.md#22-limitations-whole-project).

## 1. Where is the price set?

A pool's price can only move when a block lands, while Binance moves continuously. Each Binance
move leaves the pool quoting a stale price; the next block's arbitrageur trades the pool back to
Binance, and the LP, the passive market maker, is on the losing side of that trade. That loss is
LVR: the adverse-selection cost of quoting stale prices.

<img src="results/figures/01_what_is_lvr.svg" alt="Schematic in four steps: Binance moves, the pool is stale, an arbitrageur trades, the LP pays the gap">

A real episode, picked by a fixed rule (the 20 blocks with the largest Binance move on the day with
the most LVR; [methodology, Figures](docs/methodology.md#16a-figures)); animated block by block in
[`02_stale_pool_episode.gif`](results/figures/02_stale_pool_episode.gif):

<img src="results/figures/02_stale_pool_episode.svg" alt="Binance trades against the pool price per block over 32 blocks, with the gap shaded and each block's arbitrage marked by its LVR">

**Binance leads; the pool follows in the next block.** Per-block log returns of the pool and
Binance correlate 0.0602 at lag 0 and 0.5860 at lag +1 block (Binance first), then 0.2260 at +2
and 0.1301 at +3; at negative lags (pool first) the correlation stays between -0.0103 and 0.0153
([`results/leadlag.md`](results/leadlag.md)). The pool's move in a block tracks Binance's move in
the 12 s before it.

<img src="results/figures/03_pool_follows_binance.svg" alt="Three panels: the pool-Binance basis distribution with the fee band, how long gaps last, and the lead-lag correlation of returns">

**Gaps are small and closed fast.** The median absolute basis between the pool at block start and
Binance is 3.0848 bp; 0.2171 of the 659,799 blocks start outside the ±5 bp fee band
([`results/basis.md`](results/basis.md)). An AR(1) fit of the basis gives φ = 0.6877, a half-life
of 1.8517 blocks (22.2203 s). Searchers close 0.74 of the 70,290 gaps wider than 5 bp and 0.92 of
the 12,583 wider than 10 bp, with a median duration of 12 s: the first block that can react
([`results/episodes.md`](results/episodes.md)).

These results are written by `ulpe analyze` only after checks A1–A6 pass
([`results/analysis_checks.md`](results/analysis_checks.md)): every swap is re-simulated within
tolerance, the block series is complete, and trader + LP + protocol markouts sum to zero on every
swap.

*Caveat:* all of this is at block resolution (12 s) against Binance's last trade, so it shows the
pool updating at the first block that can react, not who discovers the price within a block; the
AR(1) fits one decay rate to blocks inside and outside the band.

*Limitation:* there is no order-book data for the window, so the reference is the last trade, not
a mid; 73,139 swaps have a 0 s reference older than 5 s (the variant without them changes little).
Binance is the only reference venue.

## 2. Who has edge against the pool?

<img src="results/figures/04_markouts.svg" alt="Trader markout against Binance from 0 s to 1 h, one panel per flow label, with fading 95% day-bootstrap bands and all swaps dashed">

Mean trader markout against Binance in bp of notional (notional-weighted, after the 0.05% swap
fee), with the 95% day-bootstrap interval, from [`results/markouts.md`](results/markouts.md).
Flow labels: *searcher* = a contract that calls the pool directly from a transaction sent to it,
typically an arbitrage bot; the others are Uniswap's routers, aggregators, intent settlement and
other contracts ([methodology section 4](docs/methodology.md#4-flow-labels)).

| Flow label | Swaps | Notional share | 0 s | 12 s | 60 s | 300 s | 3,600 s |
|---|---|---|---|---|---|---|---|
| searcher | 253,280 | 0.75 | 2.86 [2.38, 3.50] | 3.58 [2.97, 4.41] | 3.93 [2.88, 5.45] | 3.78 [2.56, 5.46] | 6.65 [1.93, 13.88] |
| uniswap_router | 167,988 | 0.12 | -10.66 [-11.28, -10.01] | -10.49 [-11.18, -9.77] | -10.53 [-11.21, -9.83] | -10.95 [-11.93, -9.96] | -15.53 [-24.62, -9.01] |
| other_contract | 91,722 | 0.11 | -4.35 [-5.29, -3.46] | -4.50 [-5.57, -3.57] | -4.58 [-5.87, -3.50] | -4.74 [-5.91, -3.47] | -5.72 [-8.54, -2.77] |
| aggregator | 17,822 | 0.02 | -6.76 [-7.89, -5.85] | -6.54 [-7.49, -5.71] | -6.72 [-7.76, -5.85] | -6.96 [-8.18, -5.77] | -6.98 [-10.07, -4.03] |
| intent_settlement | 3,565 | 0.005 | -5.11 [-7.25, -3.25] | -4.21 [-5.98, -2.62] | -4.19 [-6.43, -2.23] | -3.33 [-6.45, -0.35] | 0.55 [-11.20, 14.49] |
| all swaps | 534,377 | | 0.25 [-0.14, 0.77] | 0.80 [0.30, 1.48] | 1.04 [0.26, 2.20] | 0.87 [0.03, 2.06] | 2.39 [-0.72, 7.69] |

- **Informed flow beats uninformed flow, trade by trade.** Searchers, 75% of notional, make
  **+2.86 bp** at the block time; flow through Uniswap's routers loses **−10.66 bp**.
- **Size matters.** Searcher swaps of $100k or more: +6.20 bp [4.98, 7.52]; searcher swaps under
  $1k: -4.38 bp. The median searcher swap is -0.57 bp: the edge sits in the larger tickets.
  Uniswap-router swaps of $100k or more: -17.16 bp [-18.24, -16.07], which includes their own price
  impact.
- **The pool's counterparties as a whole roughly break even** after the full fee: +0.25 bp at 0 s
  [-0.14, 0.77] and +0.80 bp at 12 s [0.30, 1.48]. The searchers' gains are largely paid for by the
  other flow.

**Is it the reference?** Mean bp at 0 s under each variant
([`results/markouts_robustness.md`](results/markouts_robustness.md)):

| Flow label | primary | ETHUSDT reference | t0 − 2 s | excluding references > 5 s old |
|---|---|---|---|---|
| searcher | 2.86 | 3.34 | 1.80 | 2.94 |
| uniswap_router | -10.66 | -12.83 | -10.71 | -10.78 |
| other_contract | -4.35 | -4.56 | -4.49 | -4.19 |
| aggregator | -6.76 | -7.79 | -6.72 | -6.84 |
| intent_settlement | -5.11 | -5.66 | -5.07 | -5.32 |

Every label keeps its sign in all four variants up to 5 minutes; in every variant every label's
interval excludes zero at every horizon, except intent settlement at 1 h. Reading Binance 2 s
earlier lowers the searchers' 0 s edge from 2.86 to 1.80 bp but leaves 12 s almost unchanged
(3.57 against 3.58). The ETHUSDT column also carries the USDT/USDC rate. For the LP result, see
[chapter 5](#5-is-it-the-reference-price).

*Caveat:* markouts include the fee and each swap's own price impact, so uninformed flow is
negative by construction; at 1 h the intervals widen a lot.

*Limitation:* labels are a curated list plus heuristics. `searcher` is a structural pattern, not a
verified identity, and 0.11 of notional stays `other_contract`. The day bootstrap treats days as
independent.

## 3. The arbitrage auction

How much edge was there, how much did the bots capture, and how much did they keep after paying
for block space?

<img src="results/figures/08_bots_keep.svg" alt="Waterfall from available arbitrage to what the top bots kept, and each top bot's gross against kept">

From [`results/arbitrage.md`](results/arbitrage.md) and
[`results/bot_profit.md`](results/bot_profit.md):

| Step | USD millions |
|---|---|
| Available at block starts, no Binance fee | 1.82 |
| Available with a 1 bp Binance fee | 1.45 |
| Captured: all searchers' 0 s markouts | 1.51 |
| Top bots, single-pool transactions: gross | 1.22 |
| − base fee burned | 0.01 |
| − priority fees | 0.54 |
| − direct coinbase payments | 0.86 |
| = kept (upper bound) | -0.19 |
| Same costs against the 12 s markout: gross | 1.47 |
| = kept at 12 s (upper bound) | 0.06 |

- **The edge is bid away.** The four top bot contracts' single-pool transactions made $1.22M
  gross at 0 s and paid $1.40M to block builders: builder income is 115% of gross at 0 s and 95%
  at 12 s. Per contract, the largest pays builders 1.26 times its gross; the two smallest pay 0.89
  and 0.52 times theirs and keep 8,867.73 and 38,004.34 USD.
- Captured is 0.8281 of available but not a subset of it: it also counts searchers trading after
  other swaps in the same block and strategies other than CEX-DEX arbitrage.

**Every searcher, and who receives the payment.** From
[`results/lvr_destination.md`](results/lvr_destination.md), as shares of the $4.14M of LVR on
searcher swaps (the hero figure draws this split): 47.7% went to LPs as fees, 15.9% to the
protocol, **20.5% to builders** ($848,648.09) and **14.4% to proposers** ($594,782.47), 34.8%
together; 6.2% is the gross of multi-pool transactions (not split), 0.2% gas burned, and searchers
kept **−4.9%** (−$201,569.88). Kept is negative because the builder and proposer payments
(0.3483 of searcher LVR) exceed the single-pool gross at 0 s (0.3020).

**How the proposer/builder split was tested.** A block's last transaction is its payment to the
proposer, sent by the fee recipient or by a payout address learned from chain data
([methodology section 19](docs/methodology.md#19-proposer-payment-detection)). The rule was
tested twice on blind relay holdouts, each with its bar fixed before the holdout was drawn: 95% of
the found payout-class blocks must match the relay's payment within 1 wei and pass a check that
the relay's proposer was the one paid.

| | first holdout (seed 44) | second holdout (seed 45) |
|---|---|---|
| payout-class blocks found on a relay | 289 | 290 |
| match the relay's payment within 1 wei | 289 (100%) | 290 (100%) |
| recipient check | last transaction's `to_address`: 132 (45.7%) | follows forwarders: 290 (100%) |
| decision | two-sided split kept | one split |

The first recipient check failed on one contract: 615 of its 616 failures were payments into
`0xfeeeeee…7ffc`, which passes the whole payment on. Redefining that check and re-scoring the same
blocks would have been fishing. Instead a check that follows the payment through the transaction
was written down and tagged (`forwarder-preregistered`) before a fresh holdout was drawn; it passed
290 of 290. The first decision stays on file as the record of the first test
([methodology section 20](docs/methodology.md#20-recipient-check-through-forwarders)). Blocks left
unexplained hold $630.11 (0.044%) of builder dollars.

*Caveat:* this does not mean the bots lose money. "Kept" is a small difference of large totals and
its sign depends on the horizon (−$0.19M at 0 s, +$0.06M at 12 s for the top bots). Gross is
measured against Binance's last trade at the block time; the bots' own hedge price and timing,
Binance fees, inventory and hedging are not observed.

> Builder payments are detected only as direct ETH transfers from the bot contract to the block's fee recipient within the same transaction. Payments routed elsewhere (another contract, a separate transaction in the bundle, off-chain agreements) are missed, so the reported net profit is an **upper bound** on what the bots keep. Binance-side trading fees, inventory and hedging costs are not observed.

> The split of builder payments between builder and proposer uses each block's ratio of proposer payment to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments are identified as the block's last transaction, sent by the fee recipient or by a payout address learned from chain data, and tested on a blind stratified relay sample; blocks where neither applies give the proposer the whole builder revenue.

*Limitation:* available arbitrage ignores gas, Binance depth and fees beyond the 1 bp sensitivity,
and counts a gap that stays open again at each block start. Failed bot transactions emit no swap,
so their gas is missed (another reason kept is an upper bound); multi-pool transactions are
reported gross only. bloXroute's max-profit relay, down throughout, left 188 sampled blocks and 75
and 78 blocks of the two holdouts without an answer.

## 4. The passive market maker's P&L

<img src="results/figures/06_cumulative_fees_vs_lvr.svg" alt="Cumulative LP fees, total fees and LVR over the window, with the gap shaded and the worst day annotated">

Window totals from [`results/lp_pnl.md`](results/lp_pnl.md), in USD:

| | USD |
|---|---|
| LP fees (after the protocol's quarter) | 2,644,187.17 |
| protocol fees | 881,290.13 |
| measured LVR, 0 s | 3,703,796.76 |
| measured LVR, 12 s | 4,089,325.49 |
| **LP fees − LVR (0 s)** | **−1,059,609.59** |
| LVR on searcher swaps / LP fees on searcher swaps | 4,144,118.00 / 1,976,144.85 |
| theoretical LVR, 1 s returns / 1-minute returns | 3,155,610.48 / 4,325,747.96 |

- **LP fees fall short of adverse selection by $1.06M** (95% day-bootstrap interval −$1.53M to
  −$0.71M). The protocol's quarter of the fees ($0.88M) is most of the gap: total swap fees
  ($3.53M) fell short of LVR by only $0.18M, an interval of −$0.57M to +$0.09M that includes zero.
  That matches chapter 2: the pool's counterparties as a whole roughly break even after the full
  fee.
- **Measured trade by trade, against the formula.** LVR is measured on every swap step as the
  pool's token change, fee excluded, valued at Binance: $3.70M at 0 s, $4.09M at 12 s. The formula
  of Milionis, Moallemi, Roughgarden and Zhang (2022) gives $3.16M with 1-second realised variance
  and $4.33M with 1-minute returns. It tracks the measured series day by day but sits below it on
  most days. With fees and discrete blocks the model expects arbitrageurs to earn $0.93M gross and
  pay $2.22M in fees; measured, searchers' 0 s gross was $1.51M and they paid $1.98M in LP fees
  plus $0.66M in protocol fees.
- **Volatility makes it worse.** Fees grow with volatility, but LVR grows faster
  ([`results/vol_regimes.md`](results/vol_regimes.md)):

| regime | days | mean σ, annualised | LP fees | LVR (0 s) | theory (1 s) | fees − LVR |
|---|---|---|---|---|---|---|
| low | 30 | 0.24 | 550,621.71 | 702,456.41 | 545,231.48 | -151,834.70 |
| mid | 31 | 0.39 | 842,277.63 | 1,068,876.83 | 910,782.63 | -226,599.20 |
| high | 31 | 0.57 | 1,251,287.82 | 1,932,463.52 | 1,699,596.37 | -681,175.69 |

With the protocol's fees added back, total swap fees exceed LVR on the low and mid terciles
(+31,703.62 and +54,157.72) and fall short only on the high one (−264,180.80).

<img src="results/figures/05_lvr_vs_volatility.svg" alt="Daily LVR and swap fees against daily realised volatility, log-log, with fitted slopes and the break-even volatility">

<img src="results/figures/07_measured_vs_theory.svg" alt="Daily measured LVR against the formula, before and after fees, with a 45 degree line">

**Who pays.** Against a portfolio that rebalances at Binance's price, after gas and direct
payments to block builders, the 7,874 positions active in the window lost **$1.10M**. Just-in-time
(JIT) positions, minted and burned in the same block around a swap, are the only type with a
positive total, +$3.6k, with an interval spanning zero; it comes from trading with flow that loses
to the pool, not from fees. Every other type lost 1.35 to 2.28 bp of position value per day, each
interval below zero; wallet-held NFT positions, which earned $2.57M of the $2.64M of fees, lost
−1.35 bp/day and −$1.08M. Against simply holding the deposited tokens the window total is
−$18.2M, which is mostly the window's price path, not LVR. Full table:
[`results/lp_groups.md`](results/lp_groups.md); the JIT detail, including the JIT operators' own
swaps, is in [methodology section 13](docs/methodology.md#13-pl-in-the-window).

<img src="results/figures/10_pnl_by_group.svg" alt="P&L against rebalancing in USD per $10,000 per month by LP type and range width, with 95% intervals">

**Over a whole life.** From first deposit to exit, 53.5% of the window-active positions beat
holding their deposits (median return about zero), 78% of those with a life of 180 days or more,
against 24.1% within the window ([`results/lifetime.md`](results/lifetime.md)). These shares count
positions, not dollars, and depend on each position's price path.

<img src="results/figures/12_lifetime.svg" alt="Share of positions that beat holding over their lifetime, by how long they lived and by range width">

These results are written by `ulpe lp` only after checks L1–L7 pass
([`results/lp_checks.md`](results/lp_checks.md)): every swap is reproduced bit-exactly step by step,
and the fee accumulators and every open position's stored state equal the chain's.

*Caveat:* LVR here is the loss against a portfolio that rebalances at Binance's price, not a loss
against holding. It is net of all flow: searcher swaps alone cost LPs $4.14M, and the rest of the
flow gave $0.44M back.

*Limitation:* LPs' hedges and other holdings are not observed; gas and builder payments count only
inside the window; the formula assumes geometric Brownian motion and Poisson blocks, while slots
are a fixed 12 s.

## 5. Is it the reference price?

<img src="results/figures/13_reference_and_timing.svg" alt="LP fees minus LVR against the time the reference price is read, from 5 s before to 4 s after slot start, for Binance's last trade, a trade-side mid proxy and ETHUSDT: every line is negative from 3 s before the slot onward, and the measured winning-bid times sit about 1 s after slot start">

Every number above reads Binance's last ETHUSDC trade at the block timestamp, the start of the
slot. A natural objection is that the loss comes from that choice. It mostly does not: **LPs lost
$1.06M at the block timestamp, and reading the price later only deepens it.** Winning bids reach
the relays about 1 s after slot start, where the loss is $1.31M. A mid-price proxy or a USDT
reference moves it by $0.14M at most. It turns positive only if prices are read more than 3 s
before the slot starts. And $0.88M (83%) of the gap is the protocol's cut of the fees, which no reference price
changes.

| reference, read at | LP fees − LVR | shift from the headline (95% paired interval) |
|---|---|---|
| Binance last trade, slot start (headline) | **−$1.06M** | |
| Binance trade-side mid proxy, slot start | −$0.92M | +$137k (+$119k to +$155k) |
| Binance ETHUSDT 1 s close, slot start | −$1.10M | −$41k (−$83k to +$8k) |
| Binance last trade, 1 s before | −$0.79M | +$269k (+$206k to +$339k) |
| Binance last trade, 1 s after | −$1.32M | −$260k (−$356k to −$193k) |
| Binance last trade, median winning bid (+0.98 s) | −$1.31M | |

- **When the price is read matters more than which price.** Each second near slot start moves
  the result by about $0.26M; the mid proxy moves it by $0.14M, and ETHUSDT's −$41k is within
  day-to-day noise. The three lines cross zero at 3.9 s (last trade), 3.3 s (mid proxy) and
  3.0 s (ETHUSDT, whose 1 s closes only change on whole seconds) before the slot.
- **The block timestamp is the early end of when a block is sealed.** For 561 of 1,000 sampled
  blocks, a relay that delivered the block publishes when it received the winning bid: median
  0.98 s after slot start, 10th–90th percentile 0.80 s to 2.59 s. That time is the latest a
  price could have been acted on in the block; searchers who sent bundles earlier read earlier
  prices. Past about +2 s the curve flattens.
- **The protocol fee switch turns a borderline result into a clear loss.** Before the protocol's
  quarter, total swap fees ($3.53M) nearly cover LVR ($3.70M); the protocol's $0.88M is the
  dashed line in the figure. Any reading above it means total fees beat LVR.

*Caveats:* Binance publishes no bid/ask history for 2026, so the mid is a proxy: the average of
the latest buyer-initiated and seller-initiated trades. One side goes stale, so the two are
crossed at 18% of swap times (median spread 0.12 bp). A block can be delivered by several
relays, and the timing covers the sampled blocks that Titan (490), Aestus (50) or Flashbots (21)
delivered, at least 391 of which ultrasound, the largest relay, also delivered. Missing are the
439 blocks none of the three delivered (20 of them Titan delivered but no longer lists): blocks
that went only through relays without bid history for the window, such as ultrasound, or were
found on no relay. They could be sealed at other times. The ETHUSDT row also carries the
USDT/USDC rate. Full tables:
[`results/reference_robustness.md`](results/reference_robustness.md),
[`results/block_timing.md`](results/block_timing.md) and
[`results/reference_robustness_proxy.md`](results/reference_robustness_proxy.md); method in
[`docs/methodology.md`](docs/methodology.md) section 18.

## 6. Can an LP do better?

A pre-registered test of counterfactual LP strategies: rules fixed on July 2026, results reported
on August–September (61 days). Every number in this chapter is a counterfactual that ignores how
other traders would react to a different range, fee or hedge.

### How it was pre-registered

The hypothesis was written down before any August–September strategy result existed
([spec](docs/specs/2026-10-21-strategy-experiment-design.md), section 1):

> A passive LP in this pool can't fix the loss by choosing a better range or hedging. Those change
> the risk and the gas bill, not the gap between fees and LVR. Only the fee itself moves that gap:
> its level, when it's charged, or the protocol's cut. Here's by how much, after costs, tested out
> of sample.

- **July chooses, August–September reports.** A first run on July fixed full range's
  fees ÷ LVR, r₀ = 0.729, and from it the margin δ = (1 − r₀) / 4 = 0.068; the simulated
  arbitrage's minimum profit; the LP gas costs; the calibration verdict; and the best July
  strategy. It wrote them to [`results/strategy_freeze.json`](results/strategy_freeze.json), which
  was committed (`f565e41`) and tagged `strategy-preregistered` before any August–September result
  existed. The report run reads every July value from that file and never rewrites it.
- **Two gates first** ([`results/strategy_checks.md`](results/strategy_checks.md)). S2 replays the
  window through the counterfactual pool at 5 bp with nothing replaced and reproduces the real pool
  exactly (534,377 swaps, 0 mismatches). S1 scores all 7,874 window-active positions with the new
  range formula and matches the engine within a relative 1e-9; it passes with little room (largest
  error 9.4e-10).
- **Two ratios per strategy:** fees ÷ LVR, the test metric, and the return against rebalancing in
  bp of time-weighted capital per day, after gas, re-centring trades and hedge costs. Every
  comparison is paired against full range on the same 1,000 resampled days.
- JIT is left out of the grid: it depends on seeing the order flow before the block lands, which
  is not a passive LP's choice.

*Caveat:* August–September is out of sample for every parameter, but not for the analyst: the
window's aggregate results were known when the hypothesis was written.

### Range width and re-centring: inconclusive

<img src="results/figures/14_range_test.svg" alt="Change in fees ÷ LVR against the full-range position for each re-centring rule and range width from ±10 to ±5,000 bp, with 95% paired intervals and the ±0.068 margin: daily re-centred narrow ranges sit above zero with intervals reaching past +0.068, the other rules sit at or a little below zero, and every cell narrower than ±5,000 bp is flagged as too large to be a price-taker">

Each strategy is a $1M position that takes its share of every recorded swap step without changing
the swaps (a price-taker), re-centred when the price leaves the range (*out of range*), leaves its
inner half (*band*), or at each UTC day (*daily*). Change in fees ÷ LVR against full range, with
the 95% paired interval ([`results/strategy_ranges.md`](results/strategy_ranges.md)); **bold**: not
inside ±δ = ±0.0677. Every row but ±5,000 bp is flagged (peak share of active liquidity above 5%).

| half-width | out of range | band | daily |
|---|---|---|---|
| ±10 bp | **−0.047 [−0.085, −0.008]** | **−0.061 [−0.097, −0.021]** | **+0.111 [+0.037, +0.204]** |
| ±25 bp | −0.037 [−0.066, −0.004] | **−0.044 [−0.073, −0.012]** | **+0.111 [+0.036, +0.199]** |
| ±50 bp | −0.027 [−0.049, −0.002] | −0.032 [−0.052, −0.009] | **+0.088 [+0.024, +0.169]** |
| ±100 bp | −0.008 [−0.022, +0.008] | −0.017 [−0.029, −0.004] | **+0.067 [+0.010, +0.143]** |
| ±250 bp | −0.003 [−0.011, +0.005] | −0.011 [−0.020, −0.002] | **+0.035 [−0.016, +0.105]** |
| ±500 bp | +0.005 [−0.005, +0.018] | −0.005 [−0.011, −0.001] | **+0.028 [−0.008, +0.092]** |
| ±1,000 bp | −0.001 [−0.006, +0.002] | −0.001 [−0.002, 0.000] | **+0.023 [−0.002, +0.068]** |
| ±2,500 bp | −0.002 [−0.004, 0.000] | −0.001 [−0.002, 0.000] | −0.001 [−0.003, 0.000] |
| ±5,000 bp | 0.000 [0.000, 0.000] | −0.001 [−0.002, 0.000] | −0.001 [−0.001, 0.000] |

- **Inconclusive, and it hangs on the flagged cells.** No interval lies entirely above +δ, which
  would have failed the hypothesis, but 10 of the 27 are not inside ±δ, all flagged. The three
  unflagged ±5,000 bp cells are inside.
- **Size changes the flag, not the ratio.** Fees ÷ LVR does not depend on size, and at $100k,
  where 15 cells are small enough, three of them (daily re-centring at ±250, ±500 and ±1,000 bp)
  have upper bounds of 0.105, 0.092 and 0.068, above δ: a smaller LP would not settle it either.
- **Costs decide the return.** Every re-centring strategy lost against rebalancing, and narrower
  ranges lost more: re-centring a ±10 bp range each time the price leaves it took 8,111
  re-centrings and returned **−454 bp/day**, against −0.19 for full range. Full return table:
  [`results/strategy_ranges.md`](results/strategy_ranges.md).

### Fee level: model-only (the model failed calibration)

<img src="results/figures/15_fee_curves.svg" alt="Model-only fee curves: arbitrage-side fees ÷ LVR rising with the fee from about 0.12 at 1 bp to 0.66 at 100 bp, with the dynamic rules at their average fee and the real pool's 0.43 at 5 bp; and whole-pool fees ÷ LVR at constant volume crossing 1 at about 8.6 bp, with the share of other volume the pool could lose before LPs are no better off than at 5 bp">

The fee results come from a second pool carried forward block by block at the counterfactual fee,
with a simulated arbitrage first in each block. In the July calibration this model's arbitrage
LVR was 1.38 times the measured LVR, outside the pre-registered ±15%. So the fee test is "not
tested (calibration failed)", as pre-registered, and every fee number is model-only: read the
curves for direction, not level ([`results/strategy_fees.md`](results/strategy_fees.md)).

- **At constant volume, LPs break even at about 8.6 bp**, and at that fee the pool can lose at most
  43% of its other volume before LPs are no better off than at 5 bp. That assumes removed flow takes
  its fees and LVR with it in proportion; it is the room that shortcut leaves, not a forecast.
- **The mechanism shows up, untested.** The arbitrage-side ratio rises with the fee, from 0.12 at
  1 bp to 0.66 at 100 bp. Volatility-scaled fees beat a fixed fee of the same average: k = 4 with a
  25-block half-life averages 7.1 bp and reaches 0.53, against 0.38 for a fixed 7.5 bp. An oracle
  fee that reads Binance (an upper bound, in no test) averages 37.8 bp and reaches 0.66.
- **The protocol cut is the largest single lever, and arithmetic, not a model.** Full range's
  fees ÷ LVR over August–September is 0.755 at the actual cut of 1/4, 0.906 at 1/10 and 1.007 with
  no cut.

### Hedge: changes the risk, not the edge

<img src="results/figures/16_hedge.svg" alt="Two panels, full range and the ±5,000 bp band position: mean daily P&L per $1M (symmetric-log axis, linear between −$200 and +$200) against the spread (standard deviation) of daily P&L per $1M (log axis), for unhedged, hedged daily, hourly and at 10% drift, and the rebalancing benchmark: the unhedged points sit far right with a spread of about $14k to $16k and a mean near +$3k from the price path; the hedged points sit between $160 and $2.4k of spread with means between −$182 and +$46, the hourly hedge nearest the benchmark">

The benchmark is the LP hedged continuously and for free at Binance's price, so fees − LVR is
already the hedged result: a hedge cannot change it (an identity, not a finding). Delta hedge with
the Binance ETHUSDC perpetual, $1M, 5 bp taker fee, funding included
([`results/strategy_hedge.md`](results/strategy_hedge.md), USD per $1M):

| position | hedge | mean daily P&L | SD of daily P&L | bp/day |
|---|---|---|---|---|
| full range | none | 3,355 | 16,397 | 30.06 |
| | daily | 17 | 466 | 0.15 |
| | hourly | 46 | 160 | 0.41 |
| | at 10% drift | −182 | 1,770 | −1.63 |
| | rebalancing benchmark | −21 | 39 | −0.19 |

Hedging hourly cuts the full-range position's daily spread from $16.4k to $160, about 100-fold.
The unhedged mean (+$3,355 a day) is the period's price path, not LP income.

### Verdict

Passive LP in this pool doesn't pay after the protocol's cut. Range width cannot be settled by a
price-taker test here, and costs make narrow re-centred ranges worse; the fee is the lever that
touches LVR, but the model built to test it failed calibration, so it stays untested; a hedge
changes the risk, not the edge.

*Limitation:* strategies are price-takers (24 of 27 cells hold more than 5% of active liquidity at
their peak, up to 84%); there is no routing model for flow at a higher fee; the hedge has no depth,
slippage or margin cost. Detail: [methodology section 21](docs/methodology.md#21-strategy-experiment-phase-5).

## Data

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

### Validation

Full report: [`data_validation/validation_report.md`](data_validation/validation_report.md)
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

Method summary: every definition and formula is in [`docs/methodology.md`](docs/methodology.md).

## Reproduce

Requirements:

- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- A `.env` (copy `.env.example`) with `ETH_RPC_URL` set to an **archive** Ethereum RPC, e.g. the
  Alchemy (the free tier worked for us as of Oct 2026). Keep it private: the URL contains your API
  key. The code never prints or logs the RPC URL; server-supplied error messages are passed through.
- `gcloud auth application-default login` for BigQuery, and `GCP_PROJECT` in `.env` set to your
  project. The free sandbox was enough for sub-projects 1 and 2 (as of Oct 2026); the paid queries
  of sub-project 3 need billing linked to the project.

```bash
uv sync
uv run pytest -q                  # offline; includes the real-data fixture test
uv run ulpe all --confirm-cost    # the whole pipeline: fetch anything missing, build, validate, analyze, lp, figures
```

**Cost.** Sub-project 3 runs two sets of paid BigQuery queries, once each. The position history
scans about 3 TB (dry run 2.98 TB) and is billed once: its first stage writes a BigQuery table that a
re-run reuses for 7 days, and the downloaded files are skipped afterwards. The three builder
queries scan about 0.66 TB in total. A Google Cloud free-trial credit covered both for us. Without
`--confirm-cost`, `ulpe all` issues no billable BigQuery query: it runs every step whose data is
already on disk, and stops with a message at the first BigQuery step whose output is missing
(pool logs, blocks, history or builder tables). `ulpe fetch-history` on its own also refuses to
query without `--confirm-cost`; it first prints the size from a free dry run.

`uv run pytest` needs no network or credentials: tests that touch the network are marked `live` and
skipped by default. The fixture test replays the first 400 real pool events of the window against a
matching slice of the on-chain tick book and runs checks C1 and C2 on them. An end-to-end test runs
the whole analysis (checks A1–A6 and every table) on the same events, with synthetic Binance
prices and bot data, and another runs `ulpe lp`'s analysis (checks L1–L7) on a small
synthetic pool with a position opened before the window, an NFT position, a JIT position and a
flash loan. The figure tests render every figure in the light theme, from a small fixture `results/`
directory and check that a second render gives the same bytes.

`ulpe all` can also be run one step at a time, in the order below. Each fetch step skips what is
already on disk. The data foundation:

```bash
uv run ulpe fetch-logs --start 2026-07-01 --end 2026-10-01 --confirm-cost   # paid BigQuery pool logs (--dry-run reports bytes scanned)
uv run ulpe fetch-snapshot                                   # tick book at the snapshot block (RPC)
uv run ulpe fetch-samples                                    # on-chain state at 500 random blocks (RPC)
uv run ulpe fetch-cex                                        # Binance ETHUSDC trades and ETHUSDT 1s candles
uv run ulpe build                                            # raw files -> interim tables
uv run ulpe validate                                         # checks C1-C6, writes data_validation/validation_report.{md,json}
```

`validate` (and `all`) exit non-zero if any check fails. Downloaded and built data goes under
`DATA_DIR` (default `./data`) and is git-ignored.

Price discovery and markouts (sub-project 2):

```bash
uv run ulpe fetch-blocks --confirm-cost   # paid BigQuery: block fee recipients and base fees; logs in top-bot transactions
uv run ulpe fetch-transfers   # Alchemy: internal ETH transfers sent by the top bot contracts
uv run ulpe analyze           # checks A1-A6, then results/: tables, figure data, summary.json
```

`fetch-logs` and `fetch-blocks` run billable queries only with `--confirm-cost`; `--dry-run`
reports bytes scanned for free. `fetch-transfers` calls
`alchemy_getAssetTransfers`, so for that step `ETH_RPC_URL` must be an Alchemy endpoint; it caches
one file per bot contract and skips contracts already fetched. `analyze` refuses to run unless
validation passed on exactly the interim files now on disk; if a gated check (A1–A4) fails it exits
non-zero and writes no results. Its per-swap and per-block working tables go to
`DATA_DIR/processed` (git-ignored).

LP P&L and where LVR goes (sub-project 3):

```bash
uv run ulpe fetch-chain-state                  # RPC: fee state at the snapshot and the 500 sample blocks
uv run ulpe fetch-history --dry-run            # free: prints the size of the paid history query
uv run ulpe fetch-history --confirm-cost       # BigQuery, paid: pool and position-manager history since 2021
uv run ulpe fetch-chain-state                  # again: position state at both ends of the window, LP code (RPC)
uv run ulpe fetch-price-history                # Binance ETHUSDT 1-minute candles since 2021
uv run ulpe fetch-builders --dry-run          # free: prints the size of the four paid builder queries
uv run ulpe fetch-builders --confirm-cost     # BigQuery, paid (about 676 GB): builder revenue and payments
uv run ulpe fetch-payout-code                  # RPC: code of payout recipients (wallet, EIP-7702 wallet, contract)
uv run ulpe fetch-relays                       # relay data APIs: 1,000 sampled blocks, the two 600-block holdouts
uv run ulpe fetch-relays                       # again: one retry pass of the seed-45 holdout, as its stopping rule says
uv run ulpe fetch-timing                       # relay data APIs: winning-bid times for the same blocks
uv run ulpe fetch-paths                        # RPC: where each seed-45 paid/payout block's payment ends up
uv run ulpe lp                                 # checks L1-L7, then results/: tables, figure data, summary.json["lp"]
```

`fetch-chain-state` runs twice because its position part needs the history. `fetch-builders` refuses
to query without `--confirm-cost` and stops before querying if a dry run exceeds its 700 GB cap. `fetch-relays` is resumable and skips a relay
after three consecutive failed blocks. Once `fetch-builders` has run it draws each holdout and
writes it to disk before any of its relay calls (a copy of the relay file is kept first); a run
that finds the seed-45 draw already on disk retries its blocks a relay never answered. Rows of
the earlier rounds are never re-queried or changed: a write that would change them is refused.
The first `lp` after every seed-45 block has a relay row and a payment path freezes the
proposer-split decision. `lp` refuses to run unless validation passed on the interim
files on disk and the `analyze` outputs exist; if a check L1–L7 fails it writes the checks file
and no results.

Strategy experiment (Phase 5):

```bash
uv run ulpe fetch-futures   # Binance USD-M ETHUSDC funding rates and 1-minute klines (hedge)
uv run ulpe strategy        # first run: checks S1-S2, then July only -> results/strategy_freeze.json
uv run ulpe strategy        # second run: August-September from the freeze -> results/strategy_*, summary.json["strategy"]
```

`strategy` refuses to run unless `lp` has written its results. Checks S1 and S2 run first; if one
fails it writes `results/strategy_checks.md` and no results. With no freeze file it computes July
only and writes the freeze; commit it (here: tagged `strategy-preregistered`) before the second
run. The second run reads every July value from the freeze, stops if any input file it hashed
has changed, and never rewrites it; to re-run July, delete the file by hand, which shows in git.
`ulpe all` runs `strategy` once. With the committed freeze it runs the report period. Without
one, the first `ulpe all` writes the July freeze and then stops at `figures`, which asks for
`ulpe strategy` (the report results do not exist yet); commit and tag the freeze, then run
`ulpe strategy` (or `ulpe all`) again. The report run checks the freeze's input hashes; a fresh
`ulpe analyze` and `ulpe lp` rewrite the hashed processed files byte-identically (verified
2026-10-22), so re-running the pipeline keeps matching the committed freeze. `ulpe analyze` keeps `summary.json`'s `lp` and `strategy` results only when its own
results are unchanged (run timestamps aside); otherwise it drops them, so `ulpe strategy` and
`ulpe figures` refuse to run until `ulpe lp` and `ulpe strategy` run again. The fee runs use 4 worker processes by default (about 1.35 GB of memory each).

Figures:

```bash
uv run ulpe figures   # results/ -> results/figures: every figure in light SVG, the GIF and the social card
```

`figures` reads only `results/` (it needs no data download) and takes seconds. `results/figures/00_hero.png` is the repository's social preview image, set by hand under
Settings → General → Social preview.

### Repo map

```
src/uniswap_lp_economics/
  abi.py            keccak, event topics and 32-byte word encoding
  config.py         pool constants, study window and settings from .env
  events.py         decode raw pool logs into typed values
  v3math.py         Uniswap V3 tick/price math and USDC/WETH price conversions
  tickbook.py       replayable per-tick liquidity state and active liquidity
  rpc.py            JSON-RPC client with retries, Multicall3 batching, pool call codecs
  snapshot.py       read the tick book and sampled state from chain
  io.py             parquet read/write for exact integers (Int128 in memory, Decimal(38,0) on disk)
  data/
    bigquery.py     download pool logs from BigQuery, one file per month
    binance.py      checksum-verified Binance downloads and parsing
    blocks.py       block fee recipients and base fees, and logs in top-bot transactions (BigQuery)
    transfers.py    top-bot internal ETH transfers (Alchemy), one cached file per contract
    history.py      pool and position-manager history since 2021: one paid, two-stage BigQuery fetch
    chain_state.py  fee and position state at the snapshot, sample and end blocks; LP code (RPC)
    builders.py     builder revenue, proposer payment and per-transaction payments (BigQuery aggregates)
    relays.py       relay-reported proposer payments for a block sample, with a circuit breaker
    block_timing.py winning-bid times from the relays that keep bid history
    futures.py      Binance USD-M perpetual funding rates and 1-minute klines (the hedge)
  build.py          raw downloads -> interim tables (events, swaps, CEX prices)
  validate.py       checks C1-C6 and the validation report
  replay.py         public event replay: pool state after every event and at every block start
  v3swap.py         exact-integer V3 swap simulation and optimal arbitrage against a CEX price
  flows.py          flow labels from labels/addresses.csv, size buckets, top-bot selection
  align.py          as-of Binance reference prices and their age at each markout horizon
  markouts.py       per-swap markouts, grouped tables, day bootstrap, stale-reference filter
  arbprofit.py      gas, priority fees and coinbase payments per swap; gross vs kept per top bot
  discovery.py      per-block series, basis, gap episodes, lead-lag, AR(1), available arbitrage
  checks.py         analysis checks A1-A6
  report.py         results tables (CSV and markdown), summary.json, the limitation text
  analyze.py        `ulpe analyze`: validated data -> checks -> results/
  lp/               sub-projects 3 and 4: LP P&L, where LVR goes, reference robustness
    swapfees.py     exact per-swap LP and protocol fees from the step-by-step re-simulation
    state.py        fee-growth accumulators as the contract keeps them, plus USD-fee and LVR accumulators
    positions.py    positions from the full history: NFT matching, direct-key episodes, LPs
    engine.py       window replay: every swap step and liquidity event through the accumulators
    ledger.py       contract mirror (what the chain stores) and attribution per position
    pnl.py          window P&L per position and by group, gas, time-weighted value, bootstrap
    theory.py       theoretical LVR, P_trade, volatility regimes
    lifetime.py     lifetime P&L against holding
    destination.py  where LVR goes: fees, gas, builder margin, proposer payment, kept
    checks.py       checks L1-L7 and the reported checks R1-R6
    robustness.py   LP fees - LVR by reference and t0 offset, with a paired day bootstrap
    figdata.py      the stale-pool episode and the JIT block picked for the figures
    analyze.py      `ulpe lp`: validated data -> checks -> results/ and summary.json["lp"]
  strategy/         Phase 5: counterfactual LP strategies
    params.py       every pre-registered value (grids, fees, tolerances, margins)
    ranges.py       price-taker attribution per swap step, rebalancing rules, gas and trade costs
    cfpool.py       the carried-forward counterfactual pool: simulated arbitrage, fee rules
    checks.py       checks S1-S3, the replaced swaps, the sandwich count, the minimum profit
    stats.py        paired day bootstrap, pre-registered verdicts, break-even, protocol cut
    hedge.py        perpetual delta hedge: rules, funding, taker fees
    analyze.py      `ulpe strategy`: gates, the July freeze, then August-September -> results/
  viz/              `ulpe figures`: house style (style.py), results loader (data.py), registry
                    (render.py) and one module per README chapter
  cli.py            `ulpe` command-line entry point (`ulpe all` runs every step in order)
scripts/
  make_fixture.py   cut the small real-data test fixture
tests/              unit tests, the real-data fixture test and the end-to-end analysis test
  fixtures/         real pool events and tick book for the offline fixture test
labels/             curated address labels (addresses.csv) and LP vaults (lp_addresses.csv), with a source link per address
results/            committed results: tables (.md, .csv), figure_data/, figures/, summary.json, analysis, LP and strategy checks, the strategy freeze
assets/fonts/       Inter (SIL Open Font License), the figures' font
data_validation/    committed validation report (.md and .json)
docs/methodology.md every definition and formula behind results/
docs/roadmap.md     what is done, what comes next and later phases
docs/specs/        design specs for every sub-project, including the pre-registrations
```

## Further reading

- Milionis, Moallemi, Roughgarden, Zhang (2022), *Automated Market Making and Loss-Versus-Rebalancing*.
- Milionis, Moallemi, Roughgarden (2023), *Automated Market Making and Arbitrage Profits in the
  Presence of Fees*, arXiv:2305.14604 (the `P_trade` adjustment).
- Adams et al. (2021), *Uniswap v3 Core* whitepaper.
