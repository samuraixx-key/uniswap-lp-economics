# Roadmap

Where the project stands and what comes next. Each piece of work has a design spec and an
implementation plan in [`docs/superpowers/`](superpowers/); the plans are kept as execution records
and are not updated after they ship, while each spec describes what was built.

## Done

| Work | What it delivered | Spec | Plan |
|---|---|---|---|
| Sub-project 1: data foundation | Pool events, Binance prices, exact pool-state replay, checks C1–C6 | [spec](superpowers/specs/2026-10-13-data-foundation-design.md) | [plan](superpowers/plans/2026-10-13-data-foundation.md) |
| Sub-project 2: price discovery and markouts | Basis, gap episodes, lead-lag, markouts by flow, bot profit, checks A1–A6 | [spec](superpowers/specs/2026-10-13-price-discovery-markouts-design.md) | [plan](superpowers/plans/2026-10-13-price-discovery-markouts.md) |
| Sub-project 3: LP P&L and where LVR goes | Exact LP fees, LVR, P&L per position and LP type, lifetime vs holding, LVR destination, checks L1–L7 | [spec](superpowers/specs/2026-10-14-lp-pnl-lvr-design.md) | [plan](superpowers/plans/2026-10-14-lp-pnl-lvr.md) |
| Chart redesign | `ulpe figures`: 12 figures plus the hero in one house style, README as a story | [spec](superpowers/specs/2026-10-15-chart-redesign-design.md) | [plan](superpowers/plans/2026-10-15-chart-redesign.md) |
| Sub-project 4: reference and timing robustness | LP fees − LVR by reference and t0 offset with paired intervals, winning-bid times, figure 13, check R6, carried-over check fixes | [spec](superpowers/specs/2026-10-21-reference-robustness-design.md) | [plan](superpowers/plans/2026-10-21-reference-robustness.md) |
| Proposer-payment detection | Five chain-only block classes with payout addresses, a 15.2 GB last-transaction table, payout recipients typed (EIP-7702 wallets as wallets), relay retries and a blind seed-44 holdout, a pre-registered and frozen split decision (result: two-sided split kept; measured split reported, not adopted), methodology section 19 | [spec](superpowers/specs/2026-10-21-proposer-payments-design.md) | [plan](superpowers/plans/2026-10-21-proposer-payments.md) |

Later chart polish (light theme only, numbered panel headers, the two-stage hero) was merged
without a separate spec; the chart spec was updated to match.

Sub-project 4's answer: the headline holds. LP fees − LVR is −$0.92M to −$1.10M across
references at the block timestamp, −$1.31M at the median winning-bid time (+0.98 s), and turns
positive only if prices are read more than 3 s before the slot.

## Next: who keeps the profit

Proposer-payment detection measured the payments but kept the two-sided proposer/builder split:
every found holdout block of the payout rule matches the relay to the wei (289 of 289), but the
pre-registered recipient check failed (45.7%), because about half of all payments go through one
forwarding contract (`0xfeeeeee…7ffc`) whose final recipient the check cannot see. The 261 GB
trace query was dropped: $633.49 (0.044%) of builder dollars is left unexplained, too little to
move the split.

- **Recipient check through forwarders:** follow internal transfers out of forwarding contracts
  to the final recipient, write a new bar down before looking, and test it on a fresh holdout
  (seed 45). Re-testing on the 289 blocks already seen to fail would be fishing. If it passes, the
  README switches to one split; until then the hedge is the honest result.
- **Class 4 definition:** two fee recipients that never pay from themselves (`0x388c…`, Lido's
  vault, and `0x7e2a…`) have a small payout pair, which sends their other 16,967 blocks to
  "unexplained" (methodology 19.2). Fix it with the forwarder check's pre-registration, not alone.
- **bloXroute max-profit** did not answer for 263 sampled blocks (188 of the original sample, 75
  of the holdout); whether the unexplained blocks are bloXroute-built stays open.
- **OKX order book** (ETH-USDC full L2, 2.9 GB) as a true mid, if the trade-side proxy is
  questioned.
- The end-to-end synthetic world lacks a transferred NFT and exact-output / to-price swaps.
- EIP-7702 delegated EOAs must count as wallets in any new owner classification (payout
  recipients already do this).

## Later

- **Phase 5, strategy experiment:** counterfactual LP strategies (range width, rebalancing rule,
  dynamic fee, CEX hedge), labelled as counterfactuals that ignore how other traders would react,
  with costs included.
- **Phase 6, report:** `REPORT.md` plus a GitHub Pages version (question → data → method →
  results → limitations), a tagged `v1.0` release.
- **Project 2:** a funding-rate basis backtester (Hyperliquid, dYdX, Binance), in its own repo.

## Manual steps

- Social preview: upload `results/figures/00_hero.png` under Settings → General → Social preview
  (offered once the repository is public).
