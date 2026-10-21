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

Later chart polish (light theme only, numbered panel headers, the two-stage hero) was merged
without a separate spec; the chart spec was updated to match.

## Next: sub-project 4, reference and timing robustness

Design: [spec](superpowers/specs/2026-10-21-reference-robustness-design.md). Does the headline
(LP fees − LVR = −$1.06M) survive other reference prices and other clock choices?

- A reference × t0-offset table (Binance last trade, trade-side mid proxy, ETHUSDT; −5 s to +4 s)
  with paired day-bootstrap shifts, built into `ulpe lp`.
- Winning-bid times from the relays that keep history (Titan, Flashbots, Aestus), so t0 is
  measured, not assumed. 0 s stays the headline.
- Figure 13 and a README chapter "Is it the reference price?", plus the protocol-fee framing
  ($0.88M of the gap is the protocol's cut).
- Carried-over fixes: A5/A6 "reported", L1 `by_mode` order, `check_l1` default, `ulpe all`
  building positions three times, figure 12's negative label.

## After sub-project 4: who keeps the profit

These change where LVR goes, not whether LPs lost:

- **Proposer payment detection:** 16.0% of blocks fall back to "self-built" because the last
  transaction is not from the fee recipient; all 70 relay mismatches are such blocks. Detect
  payments outside the last transaction and from payout addresses (new BigQuery query, about
  261 GB, run only after confirming the cost).
- **Relay sample:** bloXroute max-profit timed out and was skipped, Flashbots was skipped after
  about 600 blocks, and the 190 blocks not found are never retried on resume.
- **OKX order book** (ETH-USDC full L2, 2.9 GB) as a true mid, if the trade-side proxy is
  questioned.
- The end-to-end synthetic world lacks a transferred NFT and exact-output / to-price swaps.
- EIP-7702 delegated EOAs must count as wallets in any new owner classification.

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
