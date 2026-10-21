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

## Next: sub-project 4, reference robustness

Does the headline (LP fees − LVR = −$1.06M) survive a different reference price and better
payment detection?

- **Other reference prices:** re-measure LVR, markouts and LP P&L against a mid price and against
  OKX, and report how far the headline numbers move.
- **Proposer payment detection:** 16.0% of blocks fall back to "self-built" because the last
  transaction is not from the fee recipient; all 70 relay mismatches are such blocks. Detect
  payments outside the last transaction and from payout addresses (new BigQuery query, about
  261 GB, run only after confirming the cost).
- **Relay sample:** bloXroute max-profit timed out and was skipped, Flashbots was skipped after
  about 600 blocks, and the 190 blocks not found are never retried on resume.
- **Carried-over fixes:**
  - EIP-7702 delegated EOAs must count as wallets in any new owner classification.
  - A5 and A6 show PASS instead of "reported" (re-run `ulpe analyze`).
  - L1's `by_mode` dict order changes between runs and churns `lp_checks` and `summary.json`
    (sort it like R3).
  - `check_l1(engine_unmatched=0)`: the default could hide the gate.
  - `ulpe all` builds positions three times.
  - The end-to-end synthetic world lacks a transferred NFT and exact-output / to-price swaps.
  - Figure 12's negative "kept" label overlaps its bar.
- **Afterwards:** re-run `ulpe analyze`, `ulpe lp` and `ulpe figures`, and check every
  data-checked title and the previews by eye.

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
