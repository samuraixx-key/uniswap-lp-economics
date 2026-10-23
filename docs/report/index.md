# Report

<p class="lead">Six questions a market maker would ask about this pool, each answered on its own
page: the answer first, then the evidence, then the caveats.</p>

<div class="grid cards" markdown>

-   **1. Where is the price set?**

    On Binance. The pool follows one block later (correlation 0.59 at +1 block).

    [Chapter 1 →](1-price.md)

-   **2. Who has edge against the pool?**

    Arbitrage bots, +2.86 bp per dollar traded; router flow loses −10.66 bp.

    [Chapter 2 →](2-edge.md)

-   **3. The arbitrage auction**

    The bots' edge is bid away: 34.8% of the LVR on their swaps ends with builders and proposers.

    [Chapter 3 →](3-auction.md)

-   **4. The passive market maker's P&L**

    LP fees fall $1.06M short of LVR; $0.88M of that is the protocol's cut.

    [Chapter 4 →](4-lp-pnl.md)

-   **5. Is it the reference price?**

    Mostly not: a later read deepens the loss, and it turns positive only 3 s before the slot.

    [Chapter 5 →](5-reference.md)

-   **6. Can an LP do better?**

    Not by range or hedge (pre-registered); the fee is the lever, but untested.

    [Chapter 6 →](6-strategies.md)

</div>
