# Who makes money trading against a Uniswap pool?

A trade-by-trade study of $7.05B of flow, measured against Binance: every one of the 534,377
swaps in the Uniswap V3 USDC/WETH 0.05% pool on Ethereum from 2026-07-01 to 2026-10-01.

[![CI](https://github.com/samuraixx-key/uniswap-lp-economics/actions/workflows/ci.yml/badge.svg)](https://github.com/samuraixx-key/uniswap-lp-economics/actions/workflows/ci.yml)

**[Read the full report on the website →](https://samuraixx-key.github.io/uniswap-lp-economics/)**

**In trading terms:** LP = passive market maker · LVR = the adverse-selection cost of quoting
stale prices · searchers = arbitrage bots · builder/proposer payments = what bots pay to get
their trades into the block.

<img src="results/figures/00_hero.svg" alt="Two-stage Sankey: the LVR on searcher swaps splits into swap fees (to LPs and the protocol) and searchers' gross profit, which, topped up by searchers' own money, ends with block builders, proposers, gas and multi-pool arbitrage">

## Three findings

- **Binance sets the price.** The pool catches up one block later (correlation 0.59 at +1 block,
  0.06 in the same block). *Caveat:* block resolution (12 s), so this shows when the pool reacts,
  not who discovers the price within a block.
- **Bots +2.86 bp, router flow −10.66 bp** per dollar traded (notional-weighted), after the 5 bp fee.
  *Caveat:* measured against Binance's last trade at the block time; the bots' edge is 1.80 bp if
  prices are read 2 s earlier.
- **LP fees fall $1.06M short of adverse selection; most of the bots' edge goes to block
  producers.** Bots keep nothing measurable at block time (−$0.20M across searcher swaps, an
  upper bound). It's a small difference of large totals whose sign flips with the horizon: for the
  top four bots, −$0.19M at 0 s and +$0.06M at 12 s. *Caveat:*
  most of the $1.06M is the protocol's quarter of the fees; before that cut, fees fall short by
  $0.18M and the interval includes zero.

## Why you can trust it (overfitting controls)

- Strategy tests and their pass/fail rules were frozen with a git tag before the strategy tests
  were run: `strategy-preregistered`
  ([freeze](results/strategy_freeze.json), [at the tag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/strategy-preregistered/results/strategy_freeze.json);
  [spec](docs/specs/2026-10-21-strategy-experiment-design.md), [at the tag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/strategy-preregistered/docs/superpowers/specs/2026-10-21-strategy-experiment-design.md)).
- A check that failed, reported as failed: the first proposer-split test, `holdout-preregistered`
  ([spec](docs/specs/2026-10-21-proposer-payments-design.md), [at the tag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/holdout-preregistered/docs/superpowers/specs/2026-10-21-proposer-payments-design.md)).
  A new check, written down before a fresh holdout, `forwarder-preregistered`
  ([spec](docs/specs/2026-10-21-forwarder-recipient-check-design.md), [at the tag](https://github.com/samuraixx-key/uniswap-lp-economics/blob/forwarder-preregistered/docs/superpowers/specs/2026-10-21-forwarder-recipient-check-design.md)),
  passed 290 of 290; the first decision stays on file.
- August–September is out of sample for every parameter, but not for me: I'd seen the window's
  totals when I wrote the test.
- The range test was inconclusive; the fee model is labelled model-only after failing its July
  calibration (model LVR 1.38× measured).
- Data checks gate the analysis; re-runs reproduce every result file byte for byte (only run
  timestamps and commit ids differ).

## Would I trade it?

No. Passive LP in this pool doesn't pay after the protocol's cut. An hourly hedge cuts a
full-range position's daily P&L spread from $16.4k to $160 per $1M, which changes the risk, not
the edge.

[Full report](https://samuraixx-key.github.io/uniswap-lp-economics/report/) · [How I worked](https://samuraixx-key.github.io/uniswap-lp-economics/how/) · [Why these choices](https://samuraixx-key.github.io/uniswap-lp-economics/how/choices/) ·
[Methodology](https://samuraixx-key.github.io/uniswap-lp-economics/how/methodology/) · [Limitations](https://samuraixx-key.github.io/uniswap-lp-economics/how/limitations/) · [Reproduce](https://samuraixx-key.github.io/uniswap-lp-economics/reproduce/)

MIT licence. Research only; not financial advice.
