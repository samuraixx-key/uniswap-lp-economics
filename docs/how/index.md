# How I worked

<p class="lead">The easiest way to fool yourself in a study like this is to keep adjusting the
test until it agrees with you. Most of the process exists to stop that.</p>

## Tests were frozen before they were run

Each pre-registered test was written down, committed and tagged in git before it was run: before
its blind holdout was drawn, or before any August–September strategy result existed. The tags
are never moved, so anyone can read each rule as it stood at its commit.

| Tag | What was frozen | What happened |
|---|---|---|
| [`holdout-preregistered`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/holdout-preregistered/docs/superpowers/specs/2026-10-21-proposer-payments-design.md) | The proposer-split rule and its pass bar, before a blind relay holdout | **Failed** the recipient check (45.7%). Reported as failed; the two-sided split was kept |
| [`forwarder-preregistered`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/forwarder-preregistered/docs/superpowers/specs/2026-10-21-forwarder-recipient-check-design.md) | A new recipient check that follows payments through forwarders, before a fresh holdout | **Passed** 290 of 290, so one proposer/builder split |
| [`strategy-preregistered`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/strategy-preregistered/results/strategy_freeze.json) | Strategy tests, margins and every July value, in a freeze file | Range test **inconclusive**; fee test **not tested** (the model failed its July calibration; fee numbers are model-only) |

## A check that failed stays failed

The first recipient check failed on one forwarding contract: 615 of its 616 failures were
payments into a contract that passes the whole payment on. Rewriting the check and re-scoring the
same blocks would have been fishing. Instead the new check was written down and tagged first, and
only then was a fresh holdout drawn.

## What isn't out of sample

August–September is out of sample for every parameter, but not for me: I had seen the window's
totals when I wrote the hypothesis. The pre-registration protects the parameters, not the
question.

## Checks gate the results

Nothing is written unless the checks before it pass: data checks C1–C6 (every swap's liquidity
and tick against the chain), analysis checks A1–A4 (A5–A6 are reported), LP checks L1–L7 (every swap reproduced
bit-exactly) and strategy gates S1–S2. A re-run reproduces every result file byte for byte; only
run timestamps and commit ids differ.

<div class="grid cards" markdown>

-   [**Why these choices** →](choices.md)

    Reference price, time zero, weighting, bootstrap, benchmark and thresholds, each in a few lines.

-   [**Data and validation** →](data.md)

    Sources, what was collected, and what checks C1–C6 prove and don't.

-   [**Limitations** →](limitations.md)

    Everything the results don't cover, in one place.

-   [**Full methodology** →](methodology/index.md)

    Every definition and formula behind the results, by topic.

</div>
