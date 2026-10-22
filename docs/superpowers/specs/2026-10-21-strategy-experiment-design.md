# Phase 5: counterfactual LP strategies: design

Date: 2026-10-21, updated 2026-10-22 after the builder check and the forwarder-recipient merge.
Status: design, not built. Calls marked *(my call)* were made by the spec writer, not the user;
everything else was decided with the user. The design uses no proposer/builder split and no block
classes, so the one-split result merged on 2026-10-22 (methodology section 20) changes nothing
here; every figure quoted below was re-checked against `main` at `2fad3f9`.

## 1. Why

The headline so far: LPs in the USDC/WETH 0.05% pool earned $2.64M in fees and lost $3.70M to LVR
(0 s), fees − LVR = −$1.06M, and every passive LP type lost money against a rebalancing portfolio.
The obvious next question from a trading reader is "so what should an LP do differently?"

Most LP-strategy write-ups sweep range widths and report the best one. This phase does something
else: it says in advance which levers **cannot** close the gap, explains why, and measures the ones
that can. The sentence the phase is built to test (a hypothesis, not a result):

> A passive LP in this pool can't fix the loss by choosing a better range or hedging. Those change
> the risk and the gas bill, not the gap between fees and LVR. Only the fee itself moves that gap:
> its level, when it's charged, or the protocol's cut. Here's by how much, after costs, tested out
> of sample.

**The spec commits to reporting the result of the pre-registered test (section 7) whatever it is**:
holds, fails or inconclusive. If range width does move fees ÷ LVR, that is the finding.

Why each lever is expected to behave as it does (the argument the README will make):

- **Hedge.** The −$1.06M is already measured against a rebalancing portfolio, which is the
  continuously hedged LP. A CEX hedge cannot change fees − LVR; it only adds trading and funding
  costs. What it changes is risk: against holding, the window result is −$18.2M, against −$1.10M
  against rebalancing. So the hedge is in this phase as the **risk lever**, and it has no
  hypothesis test: "it leaves fees − LVR unchanged" is an identity of the benchmark, stated as one.
- **Range width and rebalancing.** While the price is in range, a narrower range scales fees and
  LVR by the same factor. It adds rebalancing gas, re-centring trades and out-of-range time.
  Expected: it moves costs and risk, not fees ÷ LVR.
- **Fee level and dynamic fee.** The fee is the lever that touches LVR directly: at a higher fee,
  arbitrageurs trade less often and pay more each time (`theory.p_trade`, and the theory split
  `theory_arb` against `theory_arb_fees` in sub-project 3).
- **Protocol cut.** A pool-design lever, not an LP strategy, and arithmetic, not a model. It is
  still the largest single number: $0.88M of the $1.06M gap. Reported, not tested.
- **JIT** is left out of the strategy grid: it was the one profitable LP type, but it is an active
  strategy that depends on seeing the order flow before the block lands, not a passive LP choice.

## 2. Goals, non-goals, anti-goals

**Goals**

1. A pre-registered, out-of-sample test of the hypothesis: parameters, margins, the calibration
   tolerance and every free model parameter are fixed on July 2026 (31 days); everything is
   reported on August–September 2026 (61 days) with no re-tuning.
2. Every strategy scored on two ratios (never on dollar totals, which scale with size):
   - **fees ÷ LVR**, the hypothesis metric (LP fees after the protocol's cut ÷ LVR at 0 s);
   - **return on capital against rebalancing**, in bp of time-weighted capital per day, net of
     gas, re-centring trade costs and hedge costs: the number a reader cares about.
3. Every counterfactual number is labelled as a counterfactual that ignores how other traders
   would react, **next to the number** (table caption, figure note, README sentence), not only in
   Limitations. The caveat is strongest for the fee, and the fee results carry a measured
   break-even for it (section 6.5).
4. The new machinery inherits the existing validation: two new exact checks (S1, S2) tie it to the
   engine and to the real pool before any counterfactual is run.

**Non-goals**

- No routing model: where flow would go at a higher fee (the 0.3% pool, other venues) is not
  modelled. The break-even volume loss (6.5) is reported instead.
- No large-LP model: strategies are price-takers. Their size is checked (5.4), not modelled.
- No new BigQuery queries. Only new data: Binance futures files (section 3).
- No change to any existing headline, check or table. Sub-projects 1–4 results stay as they are.

**Anti-goals (a failure even if it runs)**

- Reporting the best July strategy's July numbers, or re-tuning on August–September.
- A test that passes whatever the data say: one that rewards wide intervals, compares levels
  instead of paired differences, or counts a lever that moves the metric by construction
  (the protocol cut) as evidence.
- A fee result presented without its "traders would react" caveat and break-even beside it.
- Calibrating free parameters (read time, CEX fee, minimum profit) to make the fee model fit.

## 3. Data

Everything already on disk, plus Binance futures:

| What | Where | Used for |
|---|---|---|
| Replay inputs, swap steps, aligned swaps, block series | `data/interim/*`, `data/processed/{aligned,swap_steps,swap_fees,blocks_state}.parquet` | S1, S2, range strategies, fee model |
| Binance ETHUSDC trades | `data/raw/binance`, `data/interim/cex_ethusdc.parquet` | reference price at t0 and t0 + 1 s |
| Base fee per block | `data/raw/blocks.parquet` | gas cost of LP transactions |
| Pool transactions' other logs | `data/raw/builders/pool_tx_other_logs.parquet` | single-pool scope for all searchers (`other_logs == 0`), as `lp/destination.py` uses it |
| **New:** Binance USDⓈ-M futures funding rates and 1-minute klines (mark or last price) for the hedge instrument | data.binance.vision, checksum-verified, new `ulpe fetch-futures` | hedge costs: funding, perp–spot basis |

Hedge instrument: the ETHUSDC perpetual if data.binance.vision has funding and klines for it over
the window; otherwise ETHUSDT perpetual, with the USDT/USDC rate named as a caveat (as in
sub-project 4). The builder checks which exists before planning the fetch.

## 4. Sample split and freeze

- **July** (2026-07-01 to 2026-08-01, 31 days): calibration fit and verdict, δ, and every
  parameter choice (which dynamic-fee parameters, which strategy is "best" for the reader-facing
  table, which fee configuration is tested).
- **August–September** (2026-08-01 to 2026-10-01, 61 days): every reported number.
- **Freeze.** The first run computes July only and writes `results/strategy_freeze.json`: δ, r₀,
  the calibration verdict, every chosen parameter, the data hashes it used and the git commit.
  The August–September step refuses to run without that file and never rewrites it, as the
  proposer-split decision is frozen (`holdout_decision.json`). Re-running July with a different
  outcome requires deleting the file by hand, which shows in git.
- Strategies start on the first block of their period with fresh capital (July runs for choices,
  a fresh start on 2026-08-01 for the report) *(my call)*.
- **Honesty note for Limitations:** August–September is out of sample for every parameter, not
  for the analyst: the whole window's aggregate results (sub-projects 2–4) were known when this
  hypothesis was written.

## 5. Range width and rebalancing (price-taker positions)

### 5.1 Scoring a hypothetical position

A strategy position is a small LP that does not change the swaps: its fees and LVR are its share of
each recorded swap step, the same attribution the ledger uses (`liquidity × Δ(per-liquidity
accumulator)`). Recorded steps (`swap_steps.parquet`) are split only at initialized ticks, so a
strategy range whose bounds are not initialized ticks needs the per-step arithmetic: within a
step, liquidity is constant and the amounts between two sqrt prices follow the V3 delta formulas,
so the part of a step's fee and LVR that falls inside `[lo, hi]` is computed from the step's start
and end prices. The replay itself is not touched, so L1–L7 stay valid.

### 5.2 Check S1 (gated)

The per-step formula must reproduce the engine's own per-liquidity fee-USD and LVR(0 s)
accumulators for the ranges of real positions (every window-active position's `[tick_lower,
tick_upper]` over its active span), to a relative 1e-9 on window totals and per position *(my call:
the L6 tolerance)*. Arbitrary ranges then inherit the engine's validation.

### 5.3 The grid *(my call)*

- Widths, symmetric around the pool price at entry (and at each re-centring), rounded outward to
  tick spacing: ±10, ±25, ±50, ±100, ±250, ±500, ±1,000, ±2,500, ±5,000 bp, and full range (the
  baseline). The two widest were added after the builder check: a static ±1,000 bp range started
  on 2026-08-01 is in range for only 30.6% of August–September blocks, and the 1,000–5,000 bp
  bucket is where real LPs earned most fees.
- Rebalancing rules (not for full range):
  - **static:** never re-centred;
  - **out of range:** re-centred at the first block start after the price leaves the range;
  - **band:** re-centred when the price leaves the inner half of the range;
  - **daily:** re-centred at the first block after 00:00 UTC.
- 9 × 4 = 36 strategies plus full range.
- **Capital:** $1M at the start of each period; $100k as a sensitivity (gas is a fixed cost per
  re-centring, so return on capital depends on size).
- **Costs per re-centring:**
  - gas of one burn + collect and one mint, in gas units equal to the median of the window's NFT
    position-manager transactions of each kind, priced at the block's base fee plus the median
    priority fee of LP transactions in the window;
  - the trade that restores the new range's token ratio, done on Binance at the 0 s reference and
    charged a pre-registered taker fee of 5 bp (sensitivities 1 bp and 10 bp).
- Fees are compounded into nothing: collected fees stay as cash *(my call)*.

### 5.4 Is the LP still small?

For each strategy at each capital level, report its peak share of active liquidity. A share above
**5%** (fixed now) flags that cell as outside the price-taker assumption, in the table itself. The
cell is still reported, marked.

## 6. Fee level, dynamic fee and protocol cut (carried-forward pool)

### 6.1 The counterfactual pool

A second `TickBook` is carried from block to block (all existing math: `v3swap.swap`,
`arb_to_price`, `TickBook.apply_*`):

- **Liquidity as observed:** every Mint and Burn applies its observed liquidity at its observed
  ticks, in log order.
- **Each block:** first the simulated arbitrage (`arb_to_price` at the counterfactual fee against
  the reference at t0), then that block's other swaps re-executed at the new fee, in log order,
  each **in its own mode** as L1 recovered it (`swap_fees.mode`):
  - exact input: the observed input amount;
  - exact output: the observed output amount;
  - to price: an unlimited input stopped at the logged final price (that swap hit its limit, so
    the limit is its final price).
- The result carries into the next block; nothing resets to the real state.
- Flash loans pay the counterfactual fee on their observed amounts *(my call)*.
- Fees and LVR per step use the same accumulators as the engine (LVR valued at the 0 s reference),
  so the full-range position's fees ÷ LVR in the counterfactual pool is read the same way as in 5.

**Which flow is replaced.** Exactly the single-pool searcher swaps: flow label `searcher` and
`other_logs == 0` in `pool_tx_other_logs` (99,890 swaps, $1,251,577 gross at 0 s, of which the four
top bots 88,002 and $1.216M). The simulated arbitrage stands for whoever closes the gap to Binance;
keeping other searchers' single-pool swaps would arbitrage the pool twice. Everything else is kept
and re-executed, **multi-pool searcher swaps included** (a named caveat: some of them are CEX-DEX
arbitrage routed through other pools). Kept flow by mode, share of its notional: exact input
92.4%, exact output 2.9%, to price 4.7%.

Caveats named next to the fee results:

- "Searcher" means a contract that receives the transaction and calls the pool, not "CEX-DEX
  arbitrage". Some replaced swaps may be sandwich legs. Count them by pattern (same sender, same
  block, opposite direction, another sender's swap between them) and report the share. Exploration:
  135 legs, −$712 gross; 100 of them non-top-bot (−$3.4k).
- L1 assigns the first mode that reproduces a swap, trying exact input first; a swap that was
  really exact output but reproduces as exact input is re-executed as exact input. At 5 bp the two
  are identical, so this cannot be seen in the data.
- The simulated arbitrage always trades first in the block; real arbitrage sometimes trades after
  other swaps.

### 6.2 Check S2: identity (gated)

Before any counterfactual: run the carried-forward book at 5 bp with **nothing replaced**,
re-executing every observed swap in its own mode. It must reproduce the real pool **exactly**:
`sqrtPriceX96`, tick and liquidity after every block equal `blocks_state.end_*`; every swap's fee
and amounts equal the logged ones; per-step totals equal `swap_steps.parquet`. Exact integers,
zero mismatches, as C1/L1. This proves the carry-forward plumbing, so calibration tests only the
arbitrage model.

### 6.3 Free parameters, fixed now

| Parameter | Primary | Sensitivity |
|---|---|---|
| Arbitrage reference | Binance last trade at t0 (block timestamp) | t0 + 1 s |
| CEX fee in `arb_to_price` | 1 bp *(my call; sub-project 2's sensitivity value)* | none |
| Minimum profit for the arbitrage to trade | the block's base fee × the median gas used by single-pool searcher transactions in July *(my call)* | none |

None of them is chosen by the calibration.

### 6.4 Check S3: calibration (July, reported, sets the fee results' label)

Run the model at 5 bp on July with the single-pool searcher swaps replaced. Compare with the
measured July values on the same replaced set:

- LVR (0 s) on those swaps (simulated arbitrage LVR vs measured single-pool searcher LVR);
- fees paid by them (simulated vs measured, before the protocol's cut).

**Pass:** both within ±15% of measured *(my call)*. The verdict is frozen in
`strategy_freeze.json`.

**If calibration fails:** the fee results are still computed and published, labelled
**model-only** in every table, figure and README sentence, and the fee part of the test (7.2) is
reported as "not tested (calibration failed)". The +1 s sensitivity is reported either way.

### 6.5 Fee configurations

- **Fee levels:** 1, 5 (baseline), 10, 30, 100 bp. The 5 bp model run is the paired baseline for
  every fee comparison, so model error cancels in the difference; the real pool is reported
  alongside.
- **Dynamic fees, on-chain inputs only** (a pool can run them without an oracle) *(my call on
  the rules and grids)*:
  - **volatility fee:** fee for a block = clamp(k × σ̂, 1 bp, 100 bp), σ̂ an EWMA of the pool's
    own block-to-block log returns; k and the EWMA half-life from a small grid, chosen on July;
  - **move fee:** fee = 5 bp + k × |pool log return over the previous block|, k from a grid
    chosen on July.
- **Oracle fee, upper bound only:** fee = max(5 bp, |basis to Binance at block start|). It uses
  Binance, which a pool does not have, so it is labelled an upper bound everywhere and does not
  count toward the test.
- **Break-even volume loss, per fee configuration:** the share x of non-arbitrage (kept) flow the
  pool could lose before the full-range LP is no better off than at 5 bp:
  `x = (R(f) − R(5 bp)) / (fees_kept(f) − LVR_kept(f))`, R = fees − LVR per unit of full-range
  liquidity. *Shortcut:* removed flow's fees and LVR scale linearly and the price path does not
  change; reported as such. This turns "ignores how traders react" into a number.
- **Protocol cut:** fees ÷ LVR and return at feeProtocol 0, 1/10 and 1/4 (the actual), on the
  real pool. Arithmetic: LP fees scale by (1 − cut)/(1 − 1/4). Reported, not tested.

## 7. The pre-registered test

All differences are **paired**: strategy minus full range on the same resampled days, 95% interval
from a day bootstrap over the 61 August–September days (1,000 draws, seed 42, one draw matrix
shared by every strategy, as in sub-project 4's paired bootstrap). fees ÷ LVR in a draw is the
ratio of the draw's summed fees and summed LVR.

**Margin.** δ = (1 − r₀) / 4, with r₀ = the full-range position's fees ÷ LVR **on July**. δ is a
quarter of the full-range LP's distance to break-even, set by formula and frozen before
August–September is computed. (At the pool-level ratio, 0.71, δ would be about 0.07; the
full-range ratio is not yet computed.)

### 7.1 Range and rebalancing part

**Eligibility** *(my call, settled after the builder check)*. A strategy counts toward the
verdict only if it is in range for at least **50%** of the August–September blocks. Ineligible
cells are reported, marked "not counted: in range X% of blocks". Reason: a static narrow range is
in range on a handful of days (±10 bp: 0.5% of blocks, 7 of 61 days), so its ratio rests on a few
days and would decide the verdict by noise. The rule uses in-range time, not the metric, so it
cannot select on the outcome.

**Undefined draws** *(my call)*. In a bootstrap draw where a strategy's summed LVR is ≤ 0, its
fees ÷ LVR is undefined. Such draws count against "inside ±δ" (a strategy with more than 2.5% of
draws undefined cannot be inside) and are left out when testing "entirely above +δ", so an
undefined draw can never produce "fails".

- **Holds** if, for **every** eligible strategy in the grid at $1M, the paired interval of
  Δ(fees ÷ LVR) lies entirely within [−δ, +δ].
- **Fails** if **any** eligible strategy's paired interval lies entirely above +δ: that strategy
  closes a meaningful part of the gap.
- **Inconclusive** otherwise (what 61 days give if they cannot resolve the question). Requiring
  every strategy inside ±δ is conservative with many strategies, which is the right direction for
  a claim that something does not matter.
- Cells flagged in 5.4 still count; if the verdict depends on a flagged cell, that is said with
  the verdict *(my call)*.

### 7.2 Fee part

**Measured on the arbitrage side only** *(my call, settled after the builder check)*. The
full-range position's per-liquidity accumulators in the counterfactual pool are split in two:
steps of the simulated arbitrage and steps of kept flow. The test metric is **arbitrage-side
fees ÷ LVR**: LP fees (after the protocol's cut) paid by the simulated arbitrage ÷ the LVR of the
simulated arbitrage, at fee f against the 5 bp model.

Why not the whole pool: kept flow is re-executed at its observed size (6.1), so its fees grow with
the fee while its LVR hardly moves. At 100 bp, kept flow alone would pay roughly $17M or more over
the window against $3.7M of LVR, so a whole-pool test would pass before August–September is run
(the second anti-goal). The arbitrage side tests the mechanism section 1 argues for and does not
depend on the fixed-volume assumption. Whole-pool fees ÷ LVR and return are still reported for
every configuration, each with its break-even volume loss (6.5) beside it.

Honest expectation, stated now: theory predicts a pass. Arbitrageurs do not trade at a loss
against the reference, so the arbitrage-side ratio rises toward 1 as the fee rises; at 5 bp,
searcher swaps paid 0.64 of their LVR in total fees. The informative output is the size of the
effect and its break-even, not the verdict alone.

- The tested configuration is **one**, chosen on July: among the fee levels and the two dynamic
  rules, the one with the highest July arbitrage-side Δ(fees ÷ LVR) against the 5 bp model *(my
  call; choosing on July avoids a best-of-several pass on August–September)*. The others are
  reported descriptively.
- **Holds** if calibration passed and the paired interval of the arbitrage-side Δ(fees ÷ LVR)
  against the 5 bp model lies entirely above +δ.
- **Fails** if calibration passed and the interval lies entirely below +δ.
- **Inconclusive** if it straddles +δ; **not tested** if calibration failed.
- The protocol cut and the oracle fee do not count.

### 7.3 Hedge

No test (section 1). Reported in 8.

The overall sentence is reported part by part (range: holds/fails/inconclusive; fee:
holds/fails/inconclusive/not tested), in the README's first paragraph for this phase.

## 8. Hedge: the risk lever

For the full-range position and the reader-facing best July strategy *(my call)*: delta-hedge the
position's ETH exposure with the perpetual (section 3), re-hedged on rules *(my call)*: never,
daily, hourly, and when the delta drifts by more than 10% of position value. Costs: the 5 bp taker
fee on each hedge trade (sensitivities 1 and 10 bp), funding on the short notional from the funding
files, and the perp–spot basis at each re-hedge from the klines. Reported per rule: mean daily
return on capital and the standard deviation of daily USD P&L per $1M, against the unhedged
position and against the rebalancing benchmark (the free continuous hedge). The text states the
identity: the hedge changes the spread, not fees − LVR.

## 9. Outputs

- `uv run ulpe strategy` (also in `ulpe all`, after `lp`): runs S1 and S2 (gated: any failure
  writes `results/strategy_checks.md` and no results), then July (freeze), then
  August–September. Refuses to run unless `lp`'s outputs exist.
- `results/strategy_checks.md` (S1, S2, S3, the size flags, the sandwich count);
  `results/strategy_ranges.md`, `strategy_fees.md`, `strategy_hedge.md`, `strategy_test.md` (the
  verdicts), CSVs alongside; `summary.json["strategy"]`; `results/strategy_freeze.json`.
- Figures in the house style (`viz/`): (a) the test figure: Δ(fees ÷ LVR) with paired intervals
  per strategy against the ±δ band, plus the chosen fee configuration against +δ; (b) fees ÷ LVR
  and return against fee level with the break-even volume loss; (c) hedge: mean against spread per
  rule. *(my call on the set; the builder may merge (a) and (b).)*
- README chapter "Can an LP do better?", findings first, each counterfactual number with its
  caveat beside it; TL;DR item 7; methodology section 21 (section 20 is the forwarder recipient
  check); roadmap moves Phase 5 to Done.
- Tests: the S1 per-step formula against the engine on the synthetic world; S2 on the real-data
  fixture; the end-to-end synthetic world gains an exact-output and a to-price swap (closes the
  roadmap's open test gap); the freeze refuses a second write.

## 10. Left to the builder

- Module layout (a `strategy/` package or modules under `lp/`), and how the price-taker positions
  are batched so the grid runs in reasonable time.
- The exact EWMA and k grids for the dynamic fees (small: at most about 10 points each), written
  into the plan before the July run.
- How the time-weighted capital is computed for return on capital (follow `pnl.time_weighted_value`).
- Figure layout within the house style.
- Small points the builder check raised as decidable while building: a to-price swap whose limit
  the counterfactual price has already passed executes nothing and is counted in S-check output;
  partial-step proration follows the V3 delta formulas (5.1); the "best July strategy" hedged in
  section 8 is the eligible cell with the highest July return on capital; gas medians as in 5.3.

## 11. Calls made by the spec writer (for the user to check)

Grid widths and rebalancing rules (5.3), including ±2,500 and ±5,000 bp; capital $1M / $100k;
5 bp taker fee for re-centring and hedge trades; gas pricing for re-centring; collected fees held
as cash; S1 tolerance 1e-9; CEX fee 1 bp and the minimum-profit rule (6.3); calibration tolerance
±15% (6.4); flash loans at the new fee; the dynamic-fee rules; eligibility at 50% of blocks in
range and the undefined-draw rule (7.1); the fee test on the arbitrage side, with the tested
configuration the July-best by that metric (7.2); hedge rules and which strategies are hedged
(8); figure set.
