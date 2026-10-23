# Strategy experiment

## 21. Strategy experiment (Phase 5)

Design: [`docs/specs/2026-10-21-strategy-experiment-design.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/docs/specs/2026-10-21-strategy-experiment-design.md).
Code: `strategy/` (every pre-registered value in `strategy/params.py`), `data/futures.py`.
Results: `results/strategy_{checks,ranges,fees,hedge,test}.md` (CSVs alongside),
`summary.json["strategy"]`, `results/strategy_freeze.json`. Every number is a counterfactual
that ignores how other traders would react to a different range, fee or hedge.

### 21.1 Periods and the freeze

July = `[2026-07-01, 2026-08-01)` (31 days) fixes the choices; the report period
`[2026-08-01, 2026-10-01)` (61 days) gives every reported number. `ulpe strategy` runs twice.
With no freeze file it computes July only and writes `results/strategy_freeze.json` (refusing if
the file exists), with the git commit and a hash of every input file: data, processed LP tables
and the futures files. That file was committed as `f565e41` and tagged `strategy-preregistered`
before the second run. The second run takes every July value from the file, stops with a message
naming it if the file cannot be read, lacks a key or was frozen on other inputs, and never
rewrites it. Frozen values:

| value | frozen | from |
|---|---|---|
| r₀, full range's fees ÷ LVR in July | 0.7292 | 21.3 |
| δ = (1 − r₀) / 4 | 0.0677 | 21.7 |
| `min_profit_gas` | 137,345 | median gas used by the distinct transactions of July's replaced swaps (21.4) |
| LP gas, mint / burn + collect | 408,316 / 208,475 gas | July medians (21.3, departure 1) |
| LP priority fee | 251,225,452 wei (0.25 gwei) | July median of those transactions' effective gas price − base fee |
| calibration (S3) | failed | 21.6 |
| best strategy | `band_5000bp`, −0.82 bp/day in July | the re-centring cell with the highest July return at $1M |

A one-day probe of S3 on 2026-07-01 (LVR ratio 1.38) was seen while the code was built. It is
July data, inside the calibration period, and nothing pre-registered was changed in response:
the 1 bp CEX fee, the minimum-profit rule and the ±15% tolerance stayed as fixed in the spec.

### 21.2 A price-taker position's share of a swap step

A strategy holds liquidity ℓ in `[tick_lower, tick_upper)` over a span of `(block, log)` order
and does not change the swaps. Each recorded step (`swap_steps.parquet`: pool liquidity L, start
and end sqrt prices, `tick_start`, `fee_usd`, `lvr_0`) is attributed by one of four cases, with
`[a, b] = [min, max]` of the step's sqrt prices and `[p_lo, p_hi]` the range's:

1. **Flat step** (a = b: a flash, or a step that does not move the price): in range iff
   `tick_lower ≤ tick_start < tick_upper`, as fee growth counts it; it then takes
   `fee_usd × ℓ / L` (a flash has no LVR). A flash with the price exactly on the lower tick is in
   range, on the upper tick out.
2. **Fully inside** (`p_lo ≤ a` and `b ≤ p_hi`): `fee_usd × ℓ / L` and `lvr_0 × ℓ / L`.
3. **Disjoint** (`b ≤ p_lo` or `p_hi ≤ a`): nothing.
4. **Partial**: the part between `max(a, p_lo)` and `min(b, p_hi)`. Per unit of liquidity
   between sqrt prices x < y (as `sqrtPriceX96 / 2^96`), the V3 delta formulas give
   `USDC = (y − x) / (x y) / 10^6` and `WETH = (y − x) / 10^18`, with `y − x` taken in integers.
   The fee share is the part's input-token amount over the whole step's (USDC for a
   `zero_for_one` step, else WETH); LVR is `ℓ × (WETH × P0 − USDC)` for `zero_for_one` and
   `ℓ × (USDC − WETH × P0)` otherwise, at the step's 0 s reference P0 (section 11's sign).

Range bounds wider than Int128 are clamped above every step price, which leaves every comparison
the same. The replay itself is not touched, so L1–L7 stay valid.

**Check S1 (gated).** Every window-active position's own range and liquidity stretches, scored
this way over its span, reproduce the engine's `fee_usd` and `lvr_0` per position and on the
window totals within a relative `1e-9 × max(1, |engine|)`: 7,874 positions, largest error
9.4e-10 (LVR) and 5.9e-10 (fees), 0 failures. The margin is thin. Real positions' bounds are
initialized ticks, so recorded steps never straddle them: S1 checks cases 1 to 3 only. Case 4
is checked by a unit test that inserts a tiny real position into a swap's path and compares the
split swap with the formula (`test_partial_step_matches_a_split_swap`).

### 21.3 Range strategies

- **Ranges.** ±w ticks (one tick ≈ 1 bp) around the block-start tick c, rounded outward to the
  10-tick spacing: `[⌊(c − w)/10⌋ × 10, ⌈(c + w)/10⌉ × 10]`, w ∈ {10, 25, 50, 100, 250, 500,
  1,000, 2,500, 5,000}; full range is ±887,270.
- **Rules**, decided on each block-start tick: *static* never re-centres; *out of range*
  re-centres when `tick < tick_lower` or `tick ≥ tick_upper`; *band* when |tick − c| > w / 2;
  *daily* at the first block of a new UTC day. A new range holds from the block start, before the
  block's simulated arbitrage and events (departure 5). 9 widths × 4 rules plus full range; the
  27 re-centring cells at $1M are the tested ones, the static cells descriptive.
- **Capital and value.** $1M (and $100k) buys the first range at the period's first block
  start, valued at the pool price and the 0 s reference. At a re-centring the old range's value at
  that block start moves into the new range: `ℓ_new = ℓ_old × V_old / V_new`, both per unit of
  liquidity at that state. Collected fees stay as cash.
- **Costs per re-centring.** Gas `(208,475 + 408,316) × (base fee + 0.25 gwei) × P_ref` and a
  5 bp taker fee (1 and 10 bp as sensitivities) on `|ΔWETH| × P_ref`, the trade that restores the
  new range's token ratio at Binance's 0 s price. The entry mint and the period-end exit are free
  for every strategy (departure 4).
- **Return.** `bp/day = Σ(fees − LVR − gas − trade) / Σ_days TWV × 10⁴`, where a day's TWV is
  the mean of the position's hourly values at the pool price in force and Binance's price
  (section 13's time-weighted value). fees ÷ LVR = Σ fees / Σ LVR (LP fees after the protocol's
  cut, LVR at 0 s). At $100k fees, LVR, trade costs and value scale by 0.1 and gas does not, so
  fees ÷ LVR is the same at both sizes.
- **Peak share.** The largest ℓ / (L + ℓ) over the attributed steps; above 5% flags the cell
  as outside the price-taker assumption (flagged cells are still counted). In-range share: the
  share of the period's block starts whose tick is inside the range in force.

### 21.4 The counterfactual pool

A copy of the snapshot tick book is carried through every window block (from the snapshot, so a
report-period number sits on a pool carried through July) and never reset to the real state:

1. the fee rule sets the block's fee from the pool price at block start (the oracle rule also
   reads Binance);
2. the simulated arbitrage: `arb_to_price` at that fee with a 1 bp CEX fee against Binance's last
   trade at the block timestamp (t0 + 1 s as a sensitivity); it trades only if its profit
   exceeds `base fee × 137,345 gas × P_ref`. The step-recording swap repeats that call's own
   band-edge limit (departure 2). Its LVR is valued at the 0 s reference in both runs;
3. the block's events in log order: mints and burns as observed; the replaced swaps skipped;
   every other swap re-executed in its own L1 mode at the block's fee (exact input: the logged
   input; exact output: the logged output; to price: an unlimited input stopped at the logged
   final price); a flash loan pays `⌊paid × fee / 500⌋` on each observed amount (departure 3).

**Replaced flow:** exactly the single-pool searcher swaps, `flow_label = searcher` with
`other_logs = 0` (99,890 swaps; 33,507 in July). A to-price swap whose limit the
counterfactual price has already reached or passed executes nothing (V3 reverts it), as does a
logged swap with no input; both leave the book unchanged and are counted, never raised
(`cfpool_counts` in `summary.json`). At 5 bp over the window: 405,879 kept swaps re-executed as
exact input, 25,681 as exact output, 2,394 to price, 533 to-price swaps skipped, 0 without input,
0 unreproduced; 99,997 arbitrage trades, 15,992 gaps whose profit did not pay the gas.

Fees and LVR per step use the engine's accumulators, split by source: the full-range position's
per-liquidity fees and LVR from arbitrage steps and from kept flow (flash loans in kept).
**Arbitrage-side fees ÷ LVR** = Σ fee_arb / Σ LVR_arb (LP fees after the protocol's cut);
**whole-pool fees ÷ LVR** adds the kept side to both. The real pool's arbitrage side is read from
the replaced swaps' recorded steps.

**Check S2 (gated).** At 5 bp with nothing replaced the book must reproduce the real pool
exactly: `sqrtPriceX96`, tick and liquidity after every block equal `blocks_state.end_*`, every
step's liquidity, amounts, fees and crossed tick (flash rows included) equal `swap_steps.parquet`,
and every swap's protocol fee equals `aligned.protocol_fee_raw`. 659,799 blocks, 586,360 steps, 534,377
swaps, 0 mismatches.

### 21.5 Fee rules

| rule | fee for a block | grid |
|---|---|---|
| fixed | f | 1, 2.5, 5 (baseline), 7.5, 10, 15, 20, 30, 50, 100 bp |
| volatility | clamp(k × √EWMA(r²), 1 bp, 100 bp); r = the pool's block-to-block log return, EWMA decay 0.5^(1/h) per block, started at 0 | k ∈ {1, 2, 4}, h ∈ {25, 150, 900} blocks (about 5 min, 30 min, 3 h) |
| move | clamp(5 bp + k × \|r of the previous block\|, 1 bp, 100 bp) | k ∈ {0.5, 1, 2, 4} |
| oracle (upper bound) | clamp(max(5 bp, \|ln(P_pool / P_ref)\| at block start), 1 bp, 100 bp) | none |

Each rule is reported with its average charged fee (mean over blocks). Every grid point is
reported; none is selected on July. The fixed levels run at the 0 s and +1 s references, the
dynamic rules at 0 s.

### 21.6 Check S3: calibration (July, reported)

The 5 bp model with the replaced swaps replaced, over July, against the measured values of the
same 33,507 July swaps: the simulated arbitrage's LVR at 0 s against their measured LVR, and its
fees before the protocol's cut against theirs. Pass: both within ±15%.

| | model | measured | ratio | ratio at +1 s |
|---|---|---|---|---|
| LVR, USD | 1,509,517.58 | 1,094,192.81 | 1.3796 | 1.3285 |
| fees, USD | 787,459.32 | 746,409.12 | 1.0550 | 1.0731 |

Failed on LVR, so every fee result is labelled model-only and the fee test is "not tested
(calibration failed)". A plausible reason, not tested: the simulated arbitrage closes the whole
gap to the fee band at every block start, while real searchers captured 0.83 of the available
arbitrage (`captured_over_available`, section 7).

### 21.7 Paired bootstrap and decisions

One matrix of 1,000 draws of the 61 report days (seed 42, drawn as `theory.day_bootstrap_sum`
draws) serves every cell. Every per-day frame is joined onto the full day grid with zeros, so
draws stay paired. In a draw, a ratio is Σ numerator / Σ denominator over the drawn days; it is
undefined when the summed LVR is ≤ 0. Δ = cell − full range (range part) or rule − the 5 bp model
at the same reference (fee part), per draw; the 95% interval is the 2.5–97.5 percentiles of the
defined draws.

- **Range part** (the 27 re-centring cells at $1M, against δ = 0.0677). *Inside*: at most 2.5%
  of draws undefined, and the interval with undefined draws placed at +∞ (`inverted_cdf`
  percentiles) within [−δ, +δ]. *Above*: the defined draws' lower bound > +δ. **Holds** if every
  cell is inside, **fails** if any is above, **inconclusive** otherwise. The verdict is recomputed
  on the unflagged cells alone; if it differs, it "depends on flagged cells". Result:
  inconclusive, and it depends on the 24 flagged cells (the three unflagged, ±5,000 bp, are
  inside; no cell is above). The point estimates above +δ are daily re-centred ranges of ±10 to
  ±50 bp (+0.088 to +0.111). Such a range is out of range most of the time (±10 bp re-centred
  daily is in range at 18% of block starts), so it misses in-range LVR when the price trends away
  during the day; that reading is an interpretation, not tested.
- **Fee part**, per fixed level f > 5 bp on the arbitrage side: holds if the lower bound > +δ,
  fails if the upper bound < +δ, inconclusive otherwise; the summary is the lowest level where it
  holds, or "fails". Levels below 5 bp are not tested, and with calibration failed no level is:
  every level reads "not tested (calibration failed)". The protocol cut and the oracle fee never
  count.

### 21.8 Break-even and the protocol cut

- **X**: the lowest fee where the whole-pool fees ÷ LVR reaches 1, linear between the fixed
  levels: 8.5967 bp.
- **Break-even volume loss** per rule: `x(f) = (R(f) − R(5 bp)) / (fees_kept(f) − LVR_kept(f))`,
  R = fees − LVR per unit of full-range liquidity, the share of kept flow the pool could lose
  before the full-range LP is no better off than at 5 bp. Shortcut: removed flow's fees and LVR
  scale linearly and the price path does not change. Undefined when the denominator is ≤ 0.
  **Y** = x interpolated linearly at X on the fixed levels: 0.4256.
- **bp/day of a fee rule**: R(f) × ℓ of the $1M full-range position / that position's TWV in the
  real pool.
- **Protocol cut** (arithmetic, real pool, full range): LP fees at cut c = measured LP fees ×
  (1 − c) / (1 − 1/4), for c ∈ {0, 1/10, 1/4}; fees ÷ LVR 1.0067, 0.9061 and 0.7550.

### 21.9 Hedge

For full range and the best July strategy at $1M: a short of the position's WETH on the Binance
USDⓈ-M ETHUSDC perpetual. On the perpetual's minute grid the position's WETH `e` and value come
from the block-start state in force at each minute's close; the hedge `h` (ETH short) is reset
to `e` at the first minute and then: *never* (h = 0 throughout: unhedged), *daily* at each new UTC
day, *hourly* at each new hour, *drift* when `|e − h| × close > 10% × value`. Per minute: hedge
P&L `−h_prev × Δclose`, trade cost `|Δh| × close × taker fee` (5 bp; 1 and 10 bp); each funding
row pays `h × close × rate` on the hedge held during its minute (a positive rate pays the short).
The perp–spot basis is in the hedge P&L by construction. Daily P&L = Δ position value + fees −
gas − re-centring trades + hedge P&L + funding − hedge trades; the **rebalancing benchmark** is
fees − LVR − gas − re-centring trades with no hedge. Reported per rule: bp/day on the TWV, and the
mean and standard deviation of daily USD P&L per $1M. The hedge changes the spread, not
fees − LVR: the benchmark is the free continuous hedge.

### 21.10 Departures from the spec

<details class="note" markdown>
<summary>Each departure from the strategy spec, and why</summary>


1. **LP gas medians are July medians, frozen** (spec 5.3 says window medians). A cost input that
   feeds the July best-strategy choice must not read August–September data; `min_profit_gas` is
   treated the same way.
2. **The arbitrage's step-recording swap repeats `arb_to_price`'s own call** (its band-edge
   limit), not an exact-input swap with no limit: V3 rounds the last step differently without a
   target price. An assert that both give the same output proves it is the same swap.
3. **Flash loans at a counterfactual fee pay `⌊paid × fee / 500⌋`.** V3 rounds flash fees up, so
   this can be one raw unit low per token per flash at fees other than 5 bp (exact at 5 bp, where
   S2 checks it; 57 flashes in the window).
4. **Entry and exit are free for every strategy;** only re-centrings pay gas and the taker fee
   (spec 5.3: "per re-centring"). Every strategy, full range included, would pay the same one
   mint and one exit, so no difference against full range changes.
5. **A re-centring segment starts at the block start**, before the block's simulated arbitrage
   and events.
6. **The fee runs use 4 worker processes by default** (about 1.35 GB of memory each), not one per
   core.
7. **The report files were regenerated once, after the freeze, to make re-runs byte-identical.**
   The first report run (`54ef24c`) summed floats per day with polars' parallel `group_by`, whose
   result changes in the last bits from run to run: a re-run differed by up to 3e-11 (on a value
   of about $10,000) with every flag and verdict the same. The daily sums now run on rows sorted
   by day, and every committed strategy report file comes from one run of that code; two
   consecutive runs are byte-identical apart from `generated_utc`. Against the first run, values
   moved by at most 2.9e-11 and no flag, verdict or frozen value changed. The freeze
   (`f565e41`) was not touched. The same fix (`io.ordered_group_by`, guarded by a test because polars does not
   promise the behaviour) covers the four sums in `ulpe analyze` and `ulpe lp` whose output varied
   between runs: label coverage, check R3, the markout day bootstrap and `lp_blocks.parquet`'s row
   order. Their results moved by at most 2e-15 relative, and every freeze-hashed input stayed
   byte-identical.


</details>
