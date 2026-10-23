# 0. Why these choices

My short answers to "why did you…?"; each links to the section with the detail.

- **Why Binance's last ETHUSDC trade as the price?** Binance leads this pool by a block
  ([section 6](methodology/discovery.md#6-price-discovery)), so it is the price an arbitrageur acts on, and ETHUSDC is the
  same pair, with no USDT/USDC rate mixed in. There is no Binance bid/ask history for 2026, so the
  last trade stands in for the mid; a trade-side mid proxy and ETHUSDT move the LP result by
  $0.14M at most ([section 2](methodology/markouts.md#2-reference-price-and-time-zero),
  [section 18](methodology/robustness.md#18-reference-and-timing-robustness-sub-project-4)).
- **Why read it at the block timestamp?** It is the start of the slot, the early end of when a
  block is sealed, and the bots' own decision and hedge times are not observed. So t0 is a
  convention, and I measure how much it matters: read 2 s earlier, the bots' edge is 1.80 bp instead
  of 2.86 bp, and LP fees − LVR turns positive only if prices are read more than 3 s before the
  slot ([section 3.4](methodology/markouts.md#34-robustness-variants), [section 18](methodology/robustness.md#18-reference-and-timing-robustness-sub-project-4)).
- **Why notional-weighted markouts?** The question is how much money changes hands: the
  weighted mean is total markout over total notional, so it adds up to the dollar totals. The
  unweighted median is reported beside it; for searchers it has the opposite sign (−0.57 bp
  against +2.86 bp) because their edge sits in the larger swaps
  ([section 3.3](methodology/markouts.md#33-aggregation-and-the-day-bootstrap)).
- **Why bootstrap over days?** Resampling whole days keeps the dependence within a day
  (volatility clusters, bot activity) inside each draw. It treats days as independent of each
  other, and that is the assumption to challenge
  ([section 3.3](methodology/markouts.md#33-aggregation-and-the-day-bootstrap)).
- **Why measure LPs against a rebalancing portfolio, not against holding?** LVR is the loss
  against a portfolio that rebalances at Binance's price, which isolates the adverse-selection cost
  of quoting a stale price. P&L against holding mostly measures the window's price path (−$18.2M in
  the window, most of it not LVR), so I report it but do not use it as the benchmark
  ([section 11](methodology/lp.md#11-measured-lvr), [section 13](methodology/lp.md#13-pl-in-the-window)).
- **Why 5% of active liquidity as the price-taker line?** The strategy test assumes a strategy
  takes its share of the recorded swaps without changing them. I check that assumption instead of
  modelling a large LP. There's no standard threshold: 5% is a judgement call I fixed before any
  result, above which a cell is flagged as outside the assumption. What protects the test is that
  it was fixed in advance, and the verdict says when it depends on flagged cells
  ([section 21.3](methodology/strategy.md#213-range-strategies), [section 21.7](methodology/strategy.md#217-paired-bootstrap-and-decisions)).
- **Why a margin of ±0.068 on fees ÷ LVR?** δ = (1 − r₀) / 4, a quarter of the full-range LP's
  July distance to break-even (r₀ = 0.7292). A quarter is also a judgement call: a difference
  smaller than a quarter of the distance to break-even wouldn't change whether the LP pays, and it
  was fixed by formula before August–September was computed ([section 21.1](methodology/strategy.md#211-periods-and-the-freeze)).
- **Why a second pre-registered check for the proposer split?** The first test's recipient check
  failed: about half of all payments pass through one forwarding contract, which the check could
  not see through, although every payment matched the relay to the wei. Changing the check after
  seeing it fail and keeping the result would have been redefining a check until it passes, so I
  wrote the new check down, tagged it, and only then drew a fresh holdout. The first decision stays
  on file ([section 19.5](methodology/destination.md#195-why-the-recipient-check-failed-a-forwarding-contract),
  [section 20](methodology/destination.md#20-recipient-check-through-forwarders)).
