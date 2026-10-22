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
| Recipient check through forwarders | A pre-registered (tag `forwarder-preregistered`) recipient check that follows payments through forwarding contracts over free RPC, the class-4 fix, a blind seed-45 holdout that cannot rewrite the published rounds; result: 290 of 290 within 1 wei and through to the relay's recipient, so one proposer/builder split (proposers 14.4%, builders 20.5% of searcher LVR); methodology section 20 | [spec](superpowers/specs/2026-10-21-forwarder-recipient-check-design.md) | [plan](superpowers/plans/2026-10-22-forwarder-recipient-check.md) |
| Phase 5 (strategy experiment), the fifth sub-project | `ulpe strategy` and `ulpe fetch-futures`: price-taker range strategies with re-centring rules and costs, a carried-forward counterfactual pool with fixed, dynamic and oracle fees, a perpetual delta hedge, gated checks S1–S2, calibration S3, a July freeze tagged `strategy-preregistered` and an August–September report, figures 14–16, methodology section 21 | [spec](superpowers/specs/2026-10-21-strategy-experiment-design.md) | [plan](superpowers/plans/2026-10-22-strategy-experiment.md) |

Later chart polish (light theme only, numbered panel headers, the two-stage hero) was merged
without a separate spec; the chart spec was updated to match.

Sub-project 4's answer: the headline holds. LP fees − LVR is −$0.92M to −$1.10M across
references at the block timestamp, −$1.31M at the median winning-bid time (+0.98 s), and turns
positive only if prices are read more than 3 s before the slot.

Phase 5's answer: the range test is inconclusive (24 of 27 cells are too large to be
price-takers; the three that are not stay inside ±δ), the fee test was not run because the model
failed its July calibration (model-only: LPs break even at about 8.6 bp at constant volume), and
an hourly hedge cuts the daily spread about 100-fold without changing fees − LVR.

## Next

Who keeps the profit is settled: proposer-payment detection kept a two-sided split when its
first pre-registered recipient check failed on a forwarding contract (45.7%), and the check that
follows the forwarder, written down before a fresh seed-45 holdout, passed 290 of 290. The README
states one split; the first decision stays on file as the record of the first test.

- **bloXroute max-profit** did not answer for 341 sampled blocks (188 of the original sample, 75
  and 78 of the two holdouts); whether the unexplained blocks are bloXroute-built stays open.
- **OKX order book** (ETH-USDC full L2, 2.9 GB) as a true mid, if the trade-side proxy is
  questioned.
- The end-to-end synthetic world lacks a transferred NFT (Phase 5 added exact-output and to-price
  swaps).
- EIP-7702 delegated EOAs must count as wallets in any new owner classification (payout
  recipients already do this).
- `ulpe analyze` rewrites `summary.json` from scratch and drops the `strategy` key until
  `ulpe strategy` runs again. That's harmless in pipeline order but a trap when running one step by
  hand. Fix it the next time `analyze` is touched: keep any existing `strategy` key on rewrite
  (a few lines plus one test).
- S1 passes on the real data with a thin margin (9.4e-10 against `S1_REL_TOL = 1e-9`). It may fail
  on another machine. The tolerance was pre-registered, so it stays as it is; note this if a re-run
  elsewhere fails S1.

## Later

- **Phase 6, report:** `REPORT.md` plus a GitHub Pages version (question → data → method →
  results → limitations), a tagged `v1.0` release. When the README becomes `REPORT.md`, trim the
  "Can an LP do better?" chapter (259 lines).
- **Project 2:** a funding-rate basis backtester (Hyperliquid, dYdX, Binance), in its own repo.

## Manual steps

- Social preview: upload `results/figures/00_hero.png` under Settings → General → Social preview
  (offered once the repository is public).
