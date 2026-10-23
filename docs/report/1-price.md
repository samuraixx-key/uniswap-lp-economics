# 1. Where is the price set?

<div class="admonition abstract" markdown>
<p class="admonition-title">The answer</p>

**On Binance.** The pool follows one block later: per-block returns correlate **0.59** with
Binance's move in the block before, and only 0.06 within the same block. The gaps this leaves are
small (median 3.08 bp) and closed fast: half of those wider than 5 bp within two blocks.

</div>

<div class="stats" markdown>
<div class="stat pos"><span class="v">0.59</span><span class="l">correlation of returns, Binance one block first</span></div>
<div class="stat"><span class="v">0.06</span><span class="l">correlation in the same block</span></div>
<div class="stat"><span class="v">3.08 bp</span><span class="l">median gap between pool and Binance at block start</span></div>
<div class="stat"><span class="v">22.2 s</span><span class="l">half-life of a gap (AR(1), 1.85 blocks)</span></div>
</div>

## How a stale quote costs the LP

A pool's price can only move when a block lands, while Binance moves continuously. Each Binance
move leaves the pool quoting a stale price; the next block's arbitrageur trades the pool back to
Binance, and the LP, the passive market maker, is on the losing side of that trade. That loss is
LVR: the adverse-selection cost of quoting stale prices.

<figure markdown>

![Schematic in four steps: Binance moves, the pool is stale, an arbitrageur trades, the LP pays the gap](../../results/figures/01_what_is_lvr.svg)

</figure>

A real episode, picked by a fixed rule (the 20 blocks with the largest Binance move on the day with
the most LVR; [methodology, Figures](../how/methodology/lp.md#16a-figures)), also
[animated block by block](../../results/figures/02_stale_pool_episode.gif):

<figure markdown>

![Binance trades against the pool price per block over 32 blocks, with the gap shaded and each block's arbitrage marked by its LVR](../../results/figures/02_stale_pool_episode.svg)

</figure>

## Binance leads; the pool follows in the next block

Per-block log returns of the pool and Binance correlate 0.06 in the same block and **0.59** one
block later (Binance first), then 0.23 at two blocks and 0.13 at three. With the pool first, the
correlation stays between −0.01 and 0.02. The pool's move in a block tracks Binance's move in the
12 s before it.

<figure markdown>

![Three panels: the pool-Binance basis distribution with the fee band, how long gaps last, and the lead-lag correlation of returns](../../results/figures/03_pool_follows_binance.svg)

</figure>

## Gaps are small and closed fast

- The median absolute gap between the pool at block start and Binance is **3.08 bp**; 21.7% of
  the 659,799 blocks start outside the ±5 bp fee band.
- An AR(1) fit of the gap gives φ = 0.69: a half-life of 1.85 blocks (22.2 s).
- Searchers close 74% of the 70,290 gaps wider than 5 bp and 92% of the 12,583 wider than 10 bp.
  Half of the gaps wider than 5 bp close within 24 s (two blocks) and half of those wider than
  10 bp within 12 s, the first block that can react.

<div class="admonition warning" markdown>
<p class="admonition-title">Read with care</p>

All of this is at block resolution (12 s) against Binance's last trade, so it shows the pool
updating at the first block that can react, not who discovers the price within a block. The AR(1)
fits one decay rate to blocks inside and outside the fee band.

</div>

<details class="note" markdown>
<summary>Limitations</summary>

There is no order-book data for the window, so the reference is the last trade, not a mid; 73,139
swaps have a 0 s reference older than 5 s (the variant without them changes little). Binance is
the only reference venue. [All limitations →](../how/limitations.md#price-discovery-and-markouts-sub-project-2)

</details>

<details class="success" markdown>
<summary>Checks A1–A4 passed before these numbers were written</summary>

`ulpe analyze` writes these results only after the gated checks A1–A4 pass (A5–A6 only report,
they have no pass rule): every swap is re-simulated within tolerance, the block series is complete, and trader + LP + protocol markouts sum to zero on
every swap.

</details>

<small>Sources: [leadlag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/leadlag.md) ·
[basis](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/basis.md) ·
[episodes](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/episodes.md) ·
[analysis checks](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/analysis_checks.md) ·
method: [price discovery](../how/methodology/discovery.md#6-price-discovery)</small>
