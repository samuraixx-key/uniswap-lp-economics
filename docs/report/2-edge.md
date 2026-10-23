# 2. Who has edge against the pool?

<div class="admonition abstract" markdown>
<p class="admonition-title">The answer</p>

**Arbitrage bots.** Searchers, 75% of notional, make **+2.86 bp** per dollar traded at the block
time, after the 0.05% fee; flow through Uniswap's routers loses **−10.66 bp**. The pool's
counterparties as a whole roughly break even: the bots' gains are largely paid for by the other
flow.

</div>

<div class="stats" markdown>
<div class="stat pos"><span class="v">+2.86 bp</span><span class="l">searchers, at the block time</span></div>
<div class="stat neg"><span class="v">−10.66 bp</span><span class="l">flow through Uniswap's routers</span></div>
<div class="stat"><span class="v">75%</span><span class="l">searchers' share of notional</span></div>
<div class="stat"><span class="v">+0.25 bp</span><span class="l">all swaps together<br>95% interval −0.14 to +0.77</span></div>
</div>

<figure markdown>
![Trader markout against Binance from 0 s to 1 h, one panel per flow label, with fading 95% day-bootstrap bands and all swaps dashed](../../results/figures/04_markouts.svg)
</figure>

## Markouts by flow

Mean trader markout against Binance in bp of notional (notional-weighted, after the 0.05% swap
fee), with the 95% day-bootstrap interval, by time after the trade. *Searcher* = a contract that
calls the pool directly from a transaction sent to it, typically an arbitrage bot; the others are
Uniswap's routers, aggregators, intent settlement and other contracts
([how flows are labelled](../how/methodology/markouts.md#4-flow-labels)).

| Flow label | Swaps | Notional share | 0 s | 12 s | 60 s | 300 s | 3,600 s |
|---|--:|--:|--:|--:|--:|--:|--:|
| searcher | 253,280 | 0.75 | **2.86** [2.38, 3.50] | 3.58 [2.97, 4.41] | 3.93 [2.88, 5.45] | 3.78 [2.56, 5.46] | 6.65 [1.93, 13.88] |
| uniswap_router | 167,988 | 0.12 | **−10.66** [−11.28, −10.01] | −10.49 [−11.18, −9.77] | −10.53 [−11.21, −9.83] | −10.95 [−11.93, −9.96] | −15.53 [−24.62, −9.01] |
| other_contract | 91,722 | 0.11 | −4.35 [−5.29, −3.46] | −4.50 [−5.57, −3.57] | −4.58 [−5.87, −3.50] | −4.74 [−5.91, −3.47] | −5.72 [−8.54, −2.77] |
| aggregator | 17,822 | 0.02 | −6.76 [−7.89, −5.85] | −6.54 [−7.49, −5.71] | −6.72 [−7.76, −5.85] | −6.96 [−8.18, −5.77] | −6.98 [−10.07, −4.03] |
| intent_settlement | 3,565 | 0.005 | −5.11 [−7.25, −3.25] | −4.21 [−5.98, −2.62] | −4.19 [−6.43, −2.23] | −3.33 [−6.45, −0.35] | 0.55 [−11.20, 14.49] |
| all swaps | 534,377 | | 0.25 [−0.14, 0.77] | 0.80 [0.30, 1.48] | 1.04 [0.26, 2.20] | 0.87 [0.03, 2.06] | 2.39 [−0.72, 7.69] |

## The edge sits in the large tickets

- Searcher swaps of $100k or more make **+6.20 bp** [4.98, 7.52]; searcher swaps under $1k lose
  −4.38 bp. The median searcher swap is −0.57 bp.
- Uniswap-router swaps of $100k or more lose −17.16 bp [−18.24, −16.07], which includes their own
  price impact.
- All flow together: +0.25 bp at 0 s [−0.14, 0.77] and +0.80 bp at 12 s [0.30, 1.48]. After the
  full fee, the pool's counterparties roughly break even.

<details class="info" markdown>
<summary>Is it the reference price? Every label keeps its sign</summary>

Mean bp at 0 s under each variant:

| Flow label | primary | ETHUSDT reference | t0 − 2 s | excluding references > 5 s old |
|---|--:|--:|--:|--:|
| searcher | 2.86 | 3.34 | 1.80 | 2.94 |
| uniswap_router | −10.66 | −12.83 | −10.71 | −10.78 |
| other_contract | −4.35 | −4.56 | −4.49 | −4.19 |
| aggregator | −6.76 | −7.79 | −6.72 | −6.84 |
| intent_settlement | −5.11 | −5.66 | −5.07 | −5.32 |

Every label keeps its sign in all four variants up to 5 minutes; in every variant every label's
interval excludes zero at every horizon, except intent settlement at 1 h. Reading Binance 2 s
earlier lowers the searchers' 0 s edge from 2.86 to 1.80 bp but leaves 12 s almost unchanged
(3.57 against 3.58). The ETHUSDT column also carries the USDT/USDC rate. For the LP result, see
chapter 5.

</details>

<div class="admonition warning" markdown>
<p class="admonition-title">Read with care</p>

Markouts include the fee and each swap's own price impact, so uninformed flow is negative by
construction. At 1 h the intervals widen a lot.

</div>

<details class="note" markdown>
<summary>Limitations</summary>

Labels are a curated list plus heuristics. `searcher` is a structural pattern, not a verified
identity, and 11% of notional stays `other_contract`. The day bootstrap treats days as independent.
[All limitations →](../how/limitations.md#price-discovery-and-markouts-sub-project-2)

</details>

<small>Sources: [markouts](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/markouts.md) ·
[markouts robustness](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/markouts_robustness.md) ·
method: [markouts](../how/methodology/markouts.md#3-markouts)</small>
