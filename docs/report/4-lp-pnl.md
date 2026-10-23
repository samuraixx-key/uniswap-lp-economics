# 4. The passive market maker's P&L

<div class="admonition abstract" markdown>
<p class="admonition-title">The answer</p>

Over the quarter, LP fees fell **$1.06M** short of LVR, the cost of quoting stale prices.
**$0.88M of that is the protocol's cut.** Before it, total swap fees fall short by only $0.18M,
and the interval includes zero.

</div>

<div class="stats" markdown>
<div class="stat pos"><span class="v">$2.64M</span><span class="l">LP fees, after the protocol's quarter</span></div>
<div class="stat"><span class="v">$0.88M</span><span class="l">the protocol's quarter of the fees</span></div>
<div class="stat"><span class="v">$3.70M</span><span class="l">LVR, measured at the block time</span></div>
<div class="stat neg"><span class="v">−$1.06M</span><span class="l">LP fees − LVR<br>95% interval −$1.53M to −$0.71M</span></div>
</div>

<figure markdown>
![Cumulative LP fees, total fees and LVR over the window, with the gap shaded and the worst day annotated](../../results/figures/06_cumulative_fees_vs_lvr.svg)
</figure>

## Fees fall short; the protocol's cut is most of the gap

LP fees fall short of adverse selection by **$1.06M** (95% day-bootstrap interval −$1.53M to
−$0.71M). The protocol's quarter of the fees ($0.88M) is most of the gap: total swap fees ($3.53M)
fell short of LVR by only $0.18M, an interval of −$0.57M to +$0.09M that includes zero. That
matches [chapter 2](2-edge.md): the pool's counterparties as a whole roughly break even after the
full fee.

<details class="info" markdown>
<summary>Window totals, in USD</summary>

| | USD |
|---|--:|
| LP fees (after the protocol's quarter) | 2,644,187.17 |
| protocol fees | 881,290.13 |
| measured LVR, 0 s | 3,703,796.76 |
| measured LVR, 12 s | 4,089,325.49 |
| **LP fees − LVR (0 s)** | **−1,059,609.59** |
| LVR on searcher swaps / LP fees on searcher swaps | 4,144,118.00 / 1,976,144.85 |
| theoretical LVR, 1 s returns / 1-minute returns | 3,155,610.48 / 4,325,747.96 |

</details>

## Measured trade by trade, against the formula

LVR is measured on every swap step as the pool's token change, fee excluded, valued at Binance:
**$3.70M** at 0 s, $4.09M at 12 s. The formula of Milionis, Moallemi, Roughgarden and Zhang (2022)
gives $3.16M with 1-second realised variance and $4.33M with 1-minute returns. It tracks the
measured series day by day but sits below it on most days.

<details class="info" markdown>
<summary>The measured LVR against the formula, day by day</summary>

<figure markdown>
![Daily measured LVR against the formula, before and after fees, with a 45 degree line](../../results/figures/07_measured_vs_theory.svg)
</figure>

With fees and discrete blocks the model expects arbitrageurs to earn $0.93M gross and pay $2.22M
in fees; measured, searchers' 0 s gross was $1.51M and they paid $1.98M in LP fees plus $0.66M in
protocol fees.

</details>

## Volatility makes it worse

Fees grow with volatility, but LVR grows faster. Days split into thirds by realised volatility:

| Volatility | Days | σ, annualised | LP fees | LVR (0 s) | Theory (1 s) | Fees − LVR |
|---|--:|--:|--:|--:|--:|--:|
| low | 30 | 0.24 | $551k | $702k | $545k | **−$152k** |
| mid | 31 | 0.39 | $842k | $1,069k | $911k | **−$227k** |
| high | 31 | 0.57 | $1,251k | $1,932k | $1,700k | **−$681k** |

With the protocol's fees added back, total swap fees beat LVR on the low and mid thirds (+$32k,
+$54k) and fall short only on the volatile third (−$264k).

<figure markdown>
![Daily LVR and swap fees against daily realised volatility, log-log, with fitted slopes and the break-even volatility](../../results/figures/05_lvr_vs_volatility.svg)
</figure>

## Who pays

Against a portfolio that rebalances at Binance's price, after gas and direct payments to block
builders, the 7,874 positions active in the window lost **$1.10M**.

- **Wallet-held NFT positions** earned $2.57M of the $2.64M of fees and lost $1.08M (−1.35 bp of
  position value a day).
- **Just-in-time (JIT) positions**, minted and burned in the same block around a swap, are the
  only type with a positive total: +$3.6k, with an interval spanning zero. It comes from trading
  with flow that loses to the pool, not from fees
  ([the JIT detail](../how/methodology/lp.md#13-pl-in-the-window), including the JIT operators'
  own swaps).
- Every other type lost 1.35 to 2.28 bp of position value a day, each interval below zero.
- Against simply holding the deposited tokens, the window total is −$18.2M: mostly the window's
  price path, not LVR.

<figure markdown>
![P&L against rebalancing in USD per $10,000 per month by LP type and range width, with 95% intervals](../../results/figures/10_pnl_by_group.svg)
</figure>

<details class="info" markdown>
<summary>Over a whole life: 53.5% of positions beat holding</summary>

From first deposit to exit, 53.5% of the window-active positions beat holding their deposits
(median return about zero): 78% of those with a life of 180 days or more, against 24.1% within the
window. These shares count positions, not dollars, and depend on each position's price path.

<figure markdown>
![Share of positions that beat holding over their lifetime, by how long they lived and by range width](../../results/figures/12_lifetime.svg)
</figure>

</details>

<div class="admonition warning" markdown>
<p class="admonition-title">Read with care</p>

- LVR here is the loss against a portfolio that **rebalances** at Binance's price, not a loss
  against holding.
- It is net of all flow: searcher swaps alone cost LPs $4.14M, and the rest of the flow gave
  $0.44M back.

</div>

<details class="note" markdown>
<summary>Limitations</summary>

LPs' hedges and other holdings are not observed; gas and builder payments count only inside the
window; the formula assumes geometric Brownian motion and Poisson blocks, while slots are a fixed
12 s. [All limitations →](../how/limitations.md#lp-pl-and-where-lvr-goes-sub-project-3)

</details>

<details class="success" markdown>
<summary>Checks L1–L7 passed before these numbers were written</summary>

`ulpe lp` writes these results only after checks L1–L7 pass: every swap is reproduced bit-exactly
step by step, and the fee accumulators and every open position's stored state equal the chain's.

</details>

<small>Sources: [LP P&L](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lp_pnl.md) ·
[volatility regimes](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/vol_regimes.md) ·
[LP groups](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lp_groups.md) ·
[lifetime](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lifetime.md) ·
[LP checks](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lp_checks.md) ·
method: [LP positions, fees and LVR](../how/methodology/lp.md#11-measured-lvr)</small>
