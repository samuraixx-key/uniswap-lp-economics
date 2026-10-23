# Reference and timing

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
by several relays: a sampled block is timed by the first of Titan, Flashbots and Aestus (in that
order) that delivered it, including many blocks ultrasound also delivered. What is missing is the
blocks none of the three delivered (or whose first delivering relay no longer lists the winning
bid, counted as `n_delivered_not_timed`; the other relays are not asked): blocks that went
only through relays without bid history, or were found on no relay. They could be sealed at
different times. Quantiles are in
`results/block_timing.md`; the 10th–90th percentile band is drawn on figure 13. The headline
stays at 0 s.

### 18.5 Check R6 (reported)

The identity summed at the headline prices plus the flash loans' LP fees equals the headline
fees − LVR, and re-reading the primary reference at 0 s moves nothing (`primary_reprice_usd`),
both within the L6 relative tolerance.
