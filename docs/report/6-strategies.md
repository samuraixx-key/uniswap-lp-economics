# 6. Can an LP do better?

<div class="admonition abstract" markdown>
<p class="admonition-title">The answer</p>

**Not shown.** In a pre-registered test, rules fixed on July and scored on August–September, the
range test was **inconclusive**, re-centring costs made narrow ranges
worse, and a hedge changed the risk, not the edge. The fee is the lever that touches LVR, but the
model built to test it failed its calibration, so that stays **untested**.

</div>

<div class="stats" markdown>
<div class="stat"><span class="v">0.729</span><span class="l">full range's fees ÷ LVR in July, fixed before the test</span></div>
<div class="stat"><span class="v">±0.068</span><span class="l">the pre-registered margin δ</span></div>
<div class="stat"><span class="v">~8.6 bp</span><span class="l">model-only break-even fee at constant volume</span></div>
<div class="stat"><span class="v">100×</span><span class="l">smaller daily P&L spread with an hourly hedge</span></div>
</div>

A pre-registered test of counterfactual LP strategies: rules fixed on July 2026, results reported
on August–September (61 days). Every number in this chapter is a counterfactual that ignores how
other traders would react to a different range, fee or hedge.

## How it was pre-registered

The hypothesis was written down before any August–September strategy result existed
([spec](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/docs/specs/2026-10-21-strategy-experiment-design.md),
section 1):

> A passive LP in this pool can't fix the loss by choosing a better range or hedging. Those change
> the risk and the gas bill, not the gap between fees and LVR. Only the fee itself moves that gap:
> its level, when it's charged, or the protocol's cut. Here's by how much, after costs, tested out
> of sample.

- **July chooses, August–September reports.** A first run on July fixed full range's
  fees ÷ LVR, r₀ = 0.729, and from it the margin δ = (1 − r₀) / 4 = 0.068; the simulated
  arbitrage's minimum profit; the LP gas costs; the calibration verdict; and the best July
  strategy. It wrote them to
  [`results/strategy_freeze.json`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/strategy_freeze.json),
  which was committed (`f565e41`) and tagged `strategy-preregistered` before any August–September
  strategy result existed. The report run reads every July value from that file and never rewrites it.
- **Two gates first.** S2 replays the window through the counterfactual pool at 5 bp with nothing
  replaced and reproduces the real pool exactly (534,377 swaps, 0 mismatches). S1 scores all 7,874
  window-active positions with the new range formula and matches the engine within a relative
  1e-9; it passes with little room (largest error 9.4e-10).
- **Two ratios per strategy:** fees ÷ LVR, the test metric, and the return against rebalancing in
  bp of time-weighted capital per day, after gas, re-centring trades and hedge costs. Every
  comparison is paired against full range on the same 1,000 resampled days.
- JIT is left out of the grid: it depends on seeing the order flow before the block lands, which
  is not a passive LP's choice.

<div class="admonition warning" markdown>
<p class="admonition-title">Read with care</p>

August–September is out of sample for every parameter, but not for the analyst: the window's
aggregate results were known when the hypothesis was written.

</div>

## Range width and re-centring: inconclusive

<figure markdown>

![Change in fees ÷ LVR against the full-range position for each re-centring rule and range width from ±10 to ±5,000 bp, with 95% paired intervals and the ±0.068 margin: daily re-centred narrow ranges sit above zero with intervals reaching past +0.068, the other rules sit at or a little below zero, and every cell narrower than ±5,000 bp is flagged as too large to be a price-taker](../../results/figures/14_range_test.svg)

</figure>

Each strategy is a $1M position that takes its share of every recorded swap step without changing
the swaps (a price-taker), re-centred when the price leaves the range (*out of range*), leaves its
inner half (*band*), or at each UTC day (*daily*).

- **Inconclusive, and it hangs on the flagged cells.** No interval lies entirely above +δ, which
  would have failed the hypothesis, but 10 of the 27 are not inside ±δ, all flagged as too large to
  be price-takers. The three unflagged ±5,000 bp cells are inside.
- **Size changes the flag, not the ratio.** Fees ÷ LVR does not depend on size, and at $100k,
  where 15 cells are small enough, three of them (daily re-centring at ±250, ±500 and ±1,000 bp)
  have upper bounds of 0.105, 0.092 and 0.068, above δ: a smaller LP would not settle it either.
- **Costs decide the return.** Every re-centring strategy lost against rebalancing, and narrower
  ranges lost more: re-centring a ±10 bp range each time the price leaves it took 8,111
  re-centrings and returned **−454 bp/day**, against −0.19 for full range.

<details class="info" markdown>
<summary>Every cell: change in fees ÷ LVR against full range</summary>

With the 95% paired interval; **bold**: not inside ±δ = ±0.0677. Every row but ±5,000 bp is
flagged (peak share of active liquidity above 5%). Full return table:
[`results/strategy_ranges.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/strategy_ranges.md).

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

</details>

## Fee level: model-only (the model failed calibration)

<figure markdown>

![Model-only fee curves: arbitrage-side fees ÷ LVR rising with the fee from about 0.12 at 1 bp to 0.66 at 100 bp, with the dynamic rules at the fee they charged the arbitrage and the real pool's 0.43 at 5 bp; and whole-pool fees ÷ LVR at constant volume crossing 1 at about 8.6 bp, with the share of other volume the pool could lose before LPs are no better off than at 5 bp](../../results/figures/15_fee_curves.svg)

</figure>

The fee results come from a second pool carried forward block by block at the counterfactual fee,
with a simulated arbitrage first in each block. In the July calibration this model's arbitrage LVR
was 1.38 times the measured LVR, outside the pre-registered ±15%. So the fee test is "not tested
(calibration failed)", as pre-registered, and every fee number is model-only: read the curves for
direction, not level.

- **At constant volume, LPs break even at about 8.6 bp**, and at that fee the pool can lose at most
  43% of its other volume before LPs are no better off than at 5 bp. That assumes removed flow
  takes its fees and LVR with it in proportion; it is the room that shortcut leaves, not a forecast.
- **The mechanism shows up, untested.** The arbitrage-side ratio rises with the fee, from 0.12 at
  1 bp to 0.66 at 100 bp. A volatility-scaled fee does better than a fixed one charging the
  arbitrage as much: k = 4 with a 25-block half-life averages 7.1 bp over blocks but charges the
  arbitrage 10.8 bp, since it is high when the arbitrage trades, and reaches 0.53, against 0.42
  for a fixed 10 bp and 0.47 for a fixed 15 bp. An oracle fee set to the gap the arbitrage would
  close is no upper bound: it leaves the arbitrage no profit below its 100 bp cap, so the arbitrage
  pays 100 bp and the rule matches the fixed 100 bp fee (0.66).
- **The protocol cut is the largest single lever, and arithmetic, not a model.** Full range's
  fees ÷ LVR over August–September is 0.755 at the actual cut of 1/4, 0.906 at 1/10 and 1.007 with
  no cut.

## Hedge: changes the risk, not the edge

<figure markdown>

![Two panels, full range and the ±5,000 bp band position: mean daily P&L per $1M (symmetric-log axis, linear between −$200 and +$200) against the spread (standard deviation) of daily P&L per $1M (log axis), for unhedged, hedged daily, hourly and at 10% drift, and the rebalancing benchmark: the unhedged points sit far right with a spread of about $14k to $16k and a mean near +$3k from the price path; the hedged points sit between $160 and $2.4k of spread with means between −$182 and +$46, the hourly hedge nearest the benchmark](../../results/figures/16_hedge.svg)

</figure>

The benchmark is the LP hedged continuously and for free at Binance's price, so fees − LVR is
already the hedged result: a hedge cannot change it (an identity, not a finding). Delta hedge with
the Binance ETHUSDC perpetual, $1M, 5 bp taker fee, funding included (USD per $1M):

| Position | Hedge | Mean daily P&L | SD of daily P&L | bp/day |
|---|---|--:|--:|--:|
| full range | none | 3,355 | 16,397 | 30.06 |
| | daily | 17 | 466 | 0.15 |
| | hourly | 46 | 160 | 0.41 |
| | at 10% drift | −182 | 1,770 | −1.63 |
| | rebalancing benchmark | −21 | 39 | −0.19 |

Hedging hourly cuts the full-range position's daily spread from $16.4k to $160, about 100-fold.
The unhedged mean (+$3,355 a day) is the period's price path, not LP income.

## Verdict

Passive LP in this pool doesn't pay after the protocol's cut. Range width cannot be settled by a
price-taker test here, and costs make narrow re-centred ranges worse; the fee is the lever that
touches LVR, but the model built to test it failed calibration, so it stays untested; a hedge
changes the risk, not the edge.

<details class="note" markdown>
<summary>Limitations</summary>

Strategies are price-takers (24 of 27 cells hold more than 5% of active liquidity at their peak,
up to 84%); there is no routing model for flow at a higher fee; the hedge has no depth, slippage or
margin cost. [All limitations →](../how/limitations.md#strategy-experiment-phase-5)

</details>

<details class="success" markdown>
<summary>Gates S1–S2 passed before these numbers were written</summary>

If S1 or S2 fails, `ulpe strategy` writes only its checks file and no results. Both passed; S1
with little room (9.4e-10 against the pre-registered 1e-9).

</details>

<small>Sources: [strategy checks](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/strategy_checks.md) ·
[ranges](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/strategy_ranges.md) ·
[fees](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/strategy_fees.md) ·
[hedge](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/strategy_hedge.md) ·
method: [strategy experiment](../how/methodology/strategy.md#21-strategy-experiment-phase-5)</small>
