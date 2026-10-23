---
hide: [navigation, toc]
---

<p class="kicker">Uniswap V3 · USDC/WETH 0.05% · July–September 2026</p>

# Who makes money trading against a Uniswap pool?

<p class="lead">Every one of the 534,377 swaps ($7.05B of flow) in Ethereum's largest USDC/WETH pool
over one quarter, marked out against Binance. A market-making question: who has edge against
the pool, who pays for it, and where the money ends up.</p>

<figure markdown>

![Two-stage Sankey: the LVR on searcher swaps splits into swap fees (to LPs and the protocol) and searchers' gross profit, which, topped up by searchers' own money, ends with block builders, proposers, gas and multi-pool arbitrage](../results/figures/00_hero.svg)

</figure>

## Three findings

<div class="grid cards" markdown>

-   **Binance sets the price**

    <span class="big">+1 block</span>
    The pool catches up one block later: returns correlate 0.59 at +1 block, 0.06 in the same block.

    <span class="caveat">Caveat: block resolution (12 s). This shows when the pool reacts, not who
    discovers the price within a block.</span>

    [Chapter 1 →](report/1-price.md)

-   **Bots have the edge**

    <span class="big"><span class="pos">+2.86 bp</span> vs <span class="neg">−10.66 bp</span></span>
    Arbitrage bots against flow through Uniswap's routers, per dollar traded (notional-weighted),
    after the 5 bp fee.

    <span class="caveat">Caveat: against Binance's last trade at the block time. Read 2 s
    earlier, the bots' edge is 1.80 bp.</span>

    [Chapter 2 →](report/2-edge.md)

-   **The LP loses; block producers collect**

    <span class="big neg">−$1.06M</span>
    LP fees fall short of adverse selection. Most of the bots' edge goes on to block builders and
    proposers; the bots keep nothing measurable at block time.

    <span class="caveat">Caveat: $0.88M of the gap is the protocol's quarter of the fees. Before
    that cut, the shortfall is $0.18M and its interval includes zero.</span>

    [Chapters 3–4 →](report/3-auction.md)

</div>

<div class="admonition question" markdown>
<p class="admonition-title">Would I trade it?</p>

**No.** Passive LP in this pool doesn't pay after the protocol's cut. An hourly hedge cuts a
full-range position's daily P&L spread from $16.4k to $160 per $1M, which changes the risk, not
the edge. [The strategy test →](report/6-strategies.md)

</div>

## Why you can trust it

<div class="grid cards" markdown>

-   :material-tag-outline: **Frozen before it was run**

    The strategy tests and the proposer-split checks, with their pass/fail rules, were tagged in
    git before they were run: before any August–September strategy result existed, and before
    each blind holdout was drawn. The window's LP totals were already known.

-   :material-close-circle-outline: **A failed check, reported as failed**

    The first proposer-split test failed. It stays on file; a new check was written down before
    a fresh holdout was drawn.

-   :material-check-all: **Gated and reproducible**

    Data checks gate every result, and a re-run reproduces every result file byte for byte.

</div>

[Read the report :material-arrow-right:](report/index.md){ .md-button .md-button--primary }
[How I worked :material-arrow-right:](how/index.md){ .md-button }
