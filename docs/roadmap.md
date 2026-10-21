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

Later chart polish (light theme only, numbered panel headers, the two-stage hero) was merged
without a separate spec; the chart spec was updated to match.

Sub-project 4's answer: the headline holds. LP fees − LVR is −$0.92M to −$1.10M across
references at the block timestamp, −$1.31M at the median winning-bid time (+0.98 s), and turns
positive only if prices are read 3.3 s or more before the slot.

## Next: who keeps the profit

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
