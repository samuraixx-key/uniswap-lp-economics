# 5. Is it the reference price?

<div class="admonition abstract" markdown>
<p class="admonition-title">The answer</p>

**Mostly not.** LPs lost $1.06M with Binance's last trade at the block timestamp, and reading the
price later only deepens it. A mid-price proxy or a USDT reference moves the result by $0.14M at
most; it turns positive only if prices are read more than 3 s before the slot starts.

</div>

<div class="stats" markdown>
<div class="stat neg"><span class="v">−$1.06M</span><span class="l">at the block timestamp (headline)</span></div>
<div class="stat neg"><span class="v">−$1.31M</span><span class="l">at the median winning bid (+0.98 s)</span></div>
<div class="stat"><span class="v">$0.26M</span><span class="l">moved by each second near slot start</span></div>
<div class="stat"><span class="v">83%</span><span class="l">of the gap is the protocol's cut, which no reference changes</span></div>
</div>

<figure markdown>
![LP fees minus LVR against the time the reference price is read, from 5 s before to 4 s after slot start, for Binance's last trade, a trade-side mid proxy and ETHUSDT: every line is negative from 3 s before the slot onward, and the measured winning-bid times sit about 1 s after slot start](../../results/figures/13_reference_and_timing.svg)
</figure>

## The objection, tested

Every number in chapters 1–4 reads Binance's last ETHUSDC trade at the block timestamp, the start
of the slot. A natural objection is that the loss comes from that choice. Winning bids reach the
relays about 1 s after slot start, where the loss is $1.31M. And $0.88M (83%) of the gap is the
protocol's cut of the fees, which no reference price changes.

| Reference, read at | LP fees − LVR | Shift from the headline (95% paired interval) |
|---|--:|---|
| Binance last trade, slot start (headline) | **−$1.06M** | |
| Binance trade-side mid proxy, slot start | −$0.92M | +$137k (+$119k to +$155k) |
| Binance ETHUSDT 1 s close, slot start | −$1.10M | −$41k (−$83k to +$8k) |
| Binance last trade, 1 s before | −$0.79M | +$269k (+$206k to +$339k) |
| Binance last trade, 1 s after | −$1.32M | −$260k (−$356k to −$193k) |
| Binance last trade, median winning bid (+0.98 s) | −$1.31M | |

## What moves it

- **When the price is read matters more than which price.** Each second near slot start moves the
  result by about $0.26M; the mid proxy moves it by $0.14M, and ETHUSDT's −$41k is within
  day-to-day noise. The three lines cross zero at 3.9 s (last trade), 3.3 s (mid proxy) and 3.0 s
  (ETHUSDT, whose 1 s closes only change on whole seconds) before the slot.
- **The block timestamp is the early end of when a block is sealed.** For 561 of 1,000 sampled
  blocks, a relay that delivered the block publishes when it received the winning bid: median
  0.98 s after slot start, 10th–90th percentile 0.80 s to 2.59 s. That time is the latest a price
  could have been acted on in the block; searchers who sent bundles earlier read earlier prices.
  Past about +2 s the curve flattens.
- **The protocol fee switch turns a borderline result into a clear loss.** Before the protocol's
  quarter, total swap fees ($3.53M) nearly cover LVR ($3.70M); the protocol's $0.88M is the dashed
  line in the figure. Any reading above it means total fees beat LVR.

<div class="admonition warning" markdown>
<p class="admonition-title">Read with care</p>

- Binance publishes no bid/ask history for 2026, so the mid is a proxy: the average of the latest
  buyer-initiated and seller-initiated trades. One side goes stale, so the two are crossed at 18%
  of swap times (median spread 0.12 bp).
- The ETHUSDT row also carries the USDT/USDC rate.

</div>

<details class="note" markdown>
<summary>Limitations: which blocks have a bid time</summary>

A block can be delivered by several relays, and the timing covers the sampled blocks that Titan
(490), Aestus (50) or Flashbots (21) delivered, at least 391 of which ultrasound, the largest relay,
also delivered. Missing are the 439 blocks none of the three delivered (20 of them Titan delivered
but no longer lists): blocks that went only through relays without bid history for the window,
such as ultrasound, or were found on no relay. They could be sealed at other times.
[All limitations →](../how/limitations.md#reference-and-timing-robustness-sub-project-4)

</details>

<small>Sources: [reference robustness](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/reference_robustness.md) ·
[block timing](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/block_timing.md) ·
[mid proxy](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/reference_robustness_proxy.md) ·
method: [reference and timing](../how/methodology/robustness.md#18-reference-and-timing-robustness-sub-project-4)</small>
