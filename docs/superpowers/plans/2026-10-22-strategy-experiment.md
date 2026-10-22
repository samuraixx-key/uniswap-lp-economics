# Phase 5: counterfactual LP strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `uv run ulpe strategy`: a pre-registered, out-of-sample test of whether range width,
rebalancing, hedging or the fee can close the LPs' fees − LVR gap, with costs, on July 2026
(choices) and August–September 2026 (every reported number).

**Architecture:** A new `strategy/` package. A carried-forward pool (`cfpool.py`) re-executes the
window block by block on its own `TickBook`, at any fee rule, with single-pool searcher swaps
optionally replaced by a simulated arbitrage; at 5 bp with nothing replaced it must reproduce the
real pool exactly (S2), and its step records (which carry each step's sqrt prices) feed the
price-taker range strategies (`ranges.py`, validated against the engine by S1). `stats.py` holds
the paired day bootstrap and the verdicts, `hedge.py` the perp hedge, `analyze.py` the July run,
the write-once freeze and the August–September run.

**Tech Stack:** Python 3.13, uv, polars, numpy, httpx, matplotlib (all already dependencies; add
none).

**Spec:** `docs/superpowers/specs/2026-10-21-strategy-experiment-design.md` (read it first; the
plan cites its sections as "spec N").

## Global Constraints

- Work on branch `strategy-experiment`; merge to `main` at the end. Pushes to the private repo
  `samuraixx-key/uniswap-lp-economics` need no confirmation; nothing public.
- Commit messages and PR text carry **no AI attribution lines** (no Co-Authored-By, no "Generated
  with").
- Never use the word spelled t-o-x-i-c-i-t-y anywhere (code, docs, figures); `grep -riE "tox[i]city"` must find nothing.
- No paid BigQuery query; the only new download is Binance USDⓈ-M futures files.
- No change to any existing headline, check or results file of sub-projects 1–4 (spec 2). `ulpe lp`
  results must be byte-identical before and after this branch, apart from the `"strategy"` key in
  `summary.json`.
- July = `[2026-07-01, 2026-08-01)`, report period = `[2026-08-01, 2026-10-01)` UTC (spec 4).
- Every pre-registered value lives in `strategy/params.py` and nowhere else (Task 1).
- Bootstrap: 1,000 draws, seed 42, one draw matrix over the report period's days shared by every
  cell (`theory.N_BOOT`, `theory.SEED`; drawn as `theory.day_bootstrap_sum` draws).
- Every counterfactual number in a table caption, figure note and README sentence carries the
  caveat that it ignores how other traders would react, next to the number (spec 2, goal 3).
- Writing style for README/methodology: findings first, plain words, honest limitations, the
  existing chapter style.

## Review Focus

1. **Zero-length steps at a range bound** (flash loans, and swap steps that do not move the
   price): attributed by the tick before the step, `tick_lower <= tick_start < tick_upper`, as fee
   growth would; a flash with the price exactly on a position's lower tick counts as in range, on
   its upper tick as out. Test in Task 4.
2. **A kept swap the counterfactual pool cannot replay as logged:** a to-price swap whose limit
   the counterfactual price has already passed (`swap` raises the SPL `ValueError`), or a logged
   swap with no input. Both execute nothing, the book is unchanged, and each is counted, never
   raised. Test in Task 2.
3. **A day on which a strategy has no in-range step, no swap or no cost:** every per-day frame is
   joined onto the full day grid of its period with zeros, so draws stay paired. A missing day row
   would silently misalign the paired bootstrap. Test in Task 6.
4. **Draws whose summed LVR is ≤ 0:** undefined, counted against "inside ±δ" and left out of
   "entirely above/below" (spec 7.1). Test in Task 6.
5. **A freeze file that does not match the inputs or cannot be read:** the report-period run
   stops with a message naming the file and never rewrites it; `write_freeze` on an existing file
   refuses. And the first run (no freeze yet) writes no report-period number at all. Tests in
   Task 9.

---

## File structure

| File | Responsibility |
|---|---|
| `src/uniswap_lp_economics/strategy/__init__.py` | package marker (one docstring line) |
| `strategy/params.py` | every pre-registered value (spec 5.3, 5.4, 6.3, 6.4, 6.5, 7, 8) |
| `strategy/cfpool.py` | carried-forward pool, fee rules, mode re-execution, simulated arbitrage, per-day aggregates |
| `strategy/ranges.py` | per-step range attribution, rebalancing segments, strategy scoring and costs |
| `strategy/stats.py` | paired day bootstrap, δ, range and fee verdicts, break-even, protocol cut |
| `strategy/hedge.py` | perp delta hedge rules and their daily P&L |
| `strategy/checks.py` | S1, S2, S3, the size flags, the sandwich count |
| `strategy/analyze.py` | `ulpe strategy`: inputs, gates, July and freeze, August–September, outputs |
| `data/futures.py` | Binance USDⓈ-M ETHUSDC funding and 1-minute klines, checksum-verified |
| `lp/state.py` (modify) | extract `step_values` from `PoolState.swap` so both replays share it |
| `cli.py` (modify) | `fetch-futures`, `strategy`; both in `ALL_STEPS` before `figures` |
| `viz/strategy.py`, `viz/render.py`, `viz/data.py` (modify) | figures 14–16 |
| `tests/lpworld.py` (modify) | an exact-output and a to-price swap (closes the roadmap test gap) |
| `tests/test_strategy_*.py`, `tests/vizfix.py` (modify) | tests |
| `README.md`, `docs/methodology.md`, `docs/roadmap.md` (modify) | the chapter, section 21, roadmap |

---

### Task 1: Pre-registered parameters

**Files:**
- Create: `src/uniswap_lp_economics/strategy/__init__.py`, `src/uniswap_lp_economics/strategy/params.py`
- Test: `tests/test_strategy_params.py`

**Interfaces:**
- Produces (all module-level constants in `strategy.params`):
  - `JULY_START_US`, `REPORT_START_US`, `REPORT_END_US: int` (UTC µs of 2026-07-01, 2026-08-01, 2026-10-01)
  - `HALF_WIDTHS_BP: tuple[int, ...] = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000)`
  - `RULES: tuple[str, ...] = ("static", "out_of_range", "band", "daily")`; `TESTED_RULES = RULES[1:]`
  - `FULL_RANGE = "full_range"`; `CAPITALS_USD = (1_000_000.0, 100_000.0)`; `PRIMARY_CAPITAL = 1_000_000.0`
  - `TAKER_FEE_BP = 5.0`; `TAKER_FEE_SENSITIVITY_BP = (1.0, 10.0)`
  - `PEAK_SHARE_FLAG = 0.05`
  - `FEE_LEVELS_BP: tuple[float, ...] = (1, 2.5, 5, 7.5, 10, 15, 20, 30, 50, 100)`; `BASELINE_FEE_BP = 5`
  - `VOL_K = (1.0, 2.0, 4.0)`; `VOL_HALF_LIFE_BLOCKS = (25, 150, 900)`; `MOVE_K = (0.5, 1.0, 2.0, 4.0)`
  - `MIN_FEE_BP = 1.0`; `MAX_FEE_BP = 100.0` (clamp for every dynamic rule)
  - `ARB_CEX_FEE_BP = 1.0`; `REF_OFFSETS_S = (0.0, 1.0)` (primary, sensitivity)
  - `CALIBRATION_TOL = 0.15`
  - `DELTA_DIVISOR = 4.0`; `UNDEFINED_MAX_SHARE = 0.025`
  - `HEDGE_RULES = ("never", "daily", "hourly", "drift")`; `HEDGE_DRIFT = 0.10`
  - `HEDGE_SYMBOL = "ETHUSDC"` (the perp exists on data.binance.vision for 2026-07..09; checked 2026-10-22)
  - `S1_REL_TOL = 1e-9`
  - `def bp_to_pips(bp: float) -> int` (`round(bp * 100)`)

The dynamic-rule grids are the spec's "written into the plan before the July run" (spec 10): a
per-block σ̂ of the pool is about 2.5 bp at 40% annual volatility, so `VOL_K` gives average fees of
roughly 2.5, 5 and 10 bp; half-lives of 25, 150 and 900 blocks are about 5 min, 30 min and 3 h.
The move fee is `5 bp + k × |previous block's pool log return in bp|`.

- [ ] **Step 1: Write the failing test** `test_pre_registered_values_are_pinned`: assert every
  constant above equals the value listed (a change to a pre-registered value must show in this
  test's diff), `bp_to_pips(2.5) == 250`, `bp_to_pips(5) == 500`, and that `REPORT_START_US -
  JULY_START_US == 31 * 86_400 * 10**6`.
- [ ] **Step 2: Run it:** `uv run pytest tests/test_strategy_params.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Write `params.py`**, one comment per group naming the spec section it pins.
- [ ] **Step 4: Run it:** same command. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "strategy: pre-registered parameters (spec 5-8)"`.

---

### Task 2: Carried-forward pool, identity replay and check S2

**Files:**
- Modify: `src/uniswap_lp_economics/lp/state.py` (extract `step_values`)
- Create: `src/uniswap_lp_economics/strategy/cfpool.py`, `src/uniswap_lp_economics/strategy/checks.py`
- Modify: `tests/lpworld.py` (two new swap kinds)
- Test: `tests/test_strategy_cfpool.py`, `tests/test_lp_state.py` (existing, must stay green)

**Interfaces:**
- Consumes: `v3swap.swap`, `v3swap.SwapRun`, `TickBook.apply_swap/apply_mint/apply_burn`,
  `lp.swapfees.protocol_cut`, `lp.state.step_lvr`, `validate.CheckResult`.
- Produces:
  - `lp.state.step_values(fee: int, amount_in: int, amount_out: int, zero_for_one: bool, fee_protocol: int, p0: float) -> tuple[int, int, float, float]` returning `(protocol_fee, lp_fee, fee_usd, lvr_0)`; `PoolState.swap` and `PoolState.flash` call it (pure refactor: every existing test passes unchanged).
  - `cfpool.FeeRule` (Protocol): `name: str`; `block_fee_pips(self, pool_price: float, p_ref: float | None) -> int`; `end_block(self, pool_price: float) -> None`.
  - `cfpool.FixedFee(pips: int)` (name `"fixed_<bp>bp"`).
  - `cfpool.CfInputs` (dataclass): `rows: list[EngineRow]` (window pool events, `iter_engine_rows` order); `book: TickBook` (snapshot; copied per run with `copy.deepcopy`); `fee_protocol: int`; `blocks: pl.DataFrame` (every window block: `block_number, ts_us, day, base_fee_wei, p_ref_0, p_ref_1` — Binance last trade at t0 and t0 + 1 s via `align.reference_at`); `swaps: dict[tuple[int, int], SwapInfo]`.
  - `cfpool.SwapInfo` (NamedTuple): `p0: float, mode: str, replaced: bool`. `mode` from `swap_fees.mode` (`"no_input"` when absent).
  - `cfpool.prepare_inputs(events: pl.DataFrame, ticks: pl.DataFrame, meta: dict[str, int], aligned: pl.DataFrame, swap_fees: pl.DataFrame, blocks_state: pl.DataFrame, blocks: pl.DataFrame, trades: pl.DataFrame, replaced: set[tuple[int, int]], end_us: int) -> CfInputs`
  - `cfpool.reexecute(book: TickBook, mode: str, amount0: int, amount1: int, sqrt_logged: int, fee_pips: int) -> SwapRun | None` — exact input = logged input, exact output = logged output, to price = unlimited input with `sqrt_logged` as limit; `None` for `no_input` and for an SPL `ValueError`.
  - `cfpool.CF_STEP_SCHEMA`: `block_number, log_index, step, zero_for_one, source` (`"arb" | "kept" | "flash"`), `ts_us, day, p0, liquidity, sqrt_start, sqrt_end, tick_start, amount_in, amount_out, fee, protocol_fee, lp_fee, crossed_tick, fee_usd, lvr_0, accrued`. Arbitrage steps use `log_index = -1`; `p0` is the price the step's `fee_usd` and `lvr_0` were valued at.
  - `cfpool.CfRun` (dataclass): `daily: pl.DataFrame` (Task 3 fills its columns), `counts: dict[str, int]`, `steps: pl.DataFrame | None`, `block_end: pl.DataFrame | None` (`block_number, sqrt_price_x96, tick, liquidity` after each block that had events).
  - `cfpool.run_pool(ci: CfInputs, rule: FeeRule, replace: bool, ref_offset_s: float = 0.0, min_profit_gas: int | None = None, keep_steps: bool = False) -> CfRun`
  - `checks.check_s2(run: CfRun, swap_steps: pl.DataFrame, blocks_state: pl.DataFrame, aligned: pl.DataFrame) -> CheckResult` (name `"S2 identity replay"`).

Replay order inside `run_pool` (spec 6.1): events in `(block, log_index)` order; at the first
event of each block (and for every block in `ci.blocks`, events or not, when `replace`), the fee is
`rule.block_fee_pips(pool_price, p_ref)` and the simulated arbitrage runs (Task 3); then each event:
mint/burn apply observed ticks and amount to the book; a swap that is `replaced` is skipped; any
other swap is `reexecute`d at the block fee and applied with `book.apply_swap(run.sqrt_price_x96,
run.tick)` (assert `book.liquidity == run.liquidity` after it: the crossing logic and the run must
agree); a flash pays `paid × fee_pips / FEE_PIPS` per token (spec 6.1, "my call") with the book's
active liquidity, as `PoolState.flash` does; `set_fee_protocol` updates `fee_protocol`. Steps get
`tick_start` = the book's tick before the step (from the run: the previous step's end tick; the
first step's is `book.tick`). `rule.end_block(pool_price)` after the block's last event.

- [ ] **Step 1: Extend the synthetic world.** In `tests/lpworld.py` add `World.swap_exact_output(block, log, eth_out)` (`swap(book, True, -eth_out)`) and `World.swap_to_price(block, log, sqrt_limit)` (`swap(book, True, HUGE, sqrt_limit)`), and in `build()` call them at blocks 13 and 14 after the existing swaps. Run `uv run pytest -q`; expected: PASS (L1 recovers both modes; fix any test that hard-codes the world's swap count by deriving it from the world).
- [ ] **Step 2: Write the failing tests** in `tests/test_strategy_cfpool.py`:
  - `test_step_values_matches_poolstate`: for one zero-for-one and one one-for-zero step, `step_values` equals the `protocol_fee, lp_fee, fee_usd, lvr_0` of the `StepRecord` `PoolState.swap` produces.
  - `test_identity_replay_reproduces_the_world`: `run_pool(prepare_inputs(<lpworld frames>), FixedFee(500), replace=False, keep_steps=True)` then `check_s2(...)` passes; `run.counts["mode_exact_output"] == 1` and `run.counts["mode_to_price"] == 1` (counts also carry `mode_exact_input`).
  - `test_identity_replay_on_the_real_fixture`: on `tests/fixtures` (modes from `reproduce_swap`, as L1 recovers them), every swap's re-executed `amount_in`, `amount_out` and final sqrt equal the logged values (0 mismatches).
  - `test_passed_limit_executes_nothing` (Review Focus 2): a book whose price is already below a to-price swap's limit for a zero-for-one swap → `reexecute` returns `None`; through `run_pool` the swap is counted in `counts["to_price_skipped"]` and the book is unchanged; a `no_input` swap is counted in `counts["no_input"]`.
  - `test_s2_fails_on_one_wrong_step`: perturb one step's `fee` in the expected `swap_steps` → `check_s2(...).passed is False` and the summary names the first mismatching `(block, log_index, step)`.
- [ ] **Step 3: Run them:** `uv run pytest tests/test_strategy_cfpool.py -q`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `step_values` (and switch `PoolState.swap`/`flash` to it), `FixedFee`, `CfInputs`, `SwapInfo`, `prepare_inputs`, `reexecute`, `run_pool` (identity path: no arbitrage yet; `daily` may be empty until Task 3), `check_s2`. S2 compares, exactly: per block `sqrt_price_x96, tick, liquidity` after the block vs `blocks_state.end_sqrt_price_x96, end_tick, end_liquidity`; per step `liquidity, amount_in, amount_out, fee, protocol_fee, lp_fee, crossed_tick, fee_usd, lvr_0` vs `swap_steps.parquet` on `(block_number, log_index, step)` (flash rows included); row counts equal. Its summary: `blocks_compared, steps_compared, mismatches, first_mismatch`.
- [ ] **Step 5: Run** `uv run pytest -q`. Expected: all PASS (existing L-check tests included).
- [ ] **Step 6: Commit** `git commit -m "strategy: carried-forward pool, mode re-execution, check S2; synthetic world gains exact-output and to-price swaps"`.
- [ ] **Step 7: Catch a `step_values` regression on real data now**, not after seven more tasks: start `uv run ulpe lp` in the background (`run_in_background`, log to the scratchpad); when it finishes, `git diff --stat results/` must show only `summary.json`'s `generated_utc` and `git_commit` lines; then `git checkout -- results/`. If any other number moved, stop and fix `step_values` before anything builds on it. Task 3 may start while it runs; Task 3's commit waits for its result.

---

### Task 3: Simulated arbitrage, fee rules, per-day aggregates, S3 and the sandwich count

**Files:**
- Modify: `src/uniswap_lp_economics/strategy/cfpool.py`, `src/uniswap_lp_economics/strategy/checks.py`
- Test: `tests/test_strategy_cfpool.py`

**Interfaces:**
- Consumes: `v3swap.arb_to_price(book, p_cex_usd, fee_pips, cex_fee_bp)`, `params`.
- Produces:
  - `cfpool.VolatilityFee(k: float, half_life_blocks: int)`, `cfpool.MoveFee(k: float)`, `cfpool.OracleFee()`; names `"vol_k<k>_h<h>"`, `"move_k<k>"`, `"oracle"`. All clamp to `[MIN_FEE_BP, MAX_FEE_BP]` and return `bp_to_pips`. `VolatilityFee` keeps an EWMA of squared block-to-block pool log returns (decay `0.5 ** (1 / half_life)`, started at 0 so the first blocks charge `MIN_FEE_BP`); fee bp = `k × sqrt(ewma) × 1e4`. `MoveFee`: `5 + k × |last block's log return| × 1e4`. `OracleFee`: `max(5, |ln(pool_price / p_ref)| × 1e4)` (spec 6.5: labelled an upper bound).
  - `cfpool.rule_grid() -> list[FeeRule]`: the 10 fixed levels, the 9 volatility and 4 move points, the oracle (24 rules).
  - `CfRun.daily` columns, one row per day of the window (zero-filled): `day, fee_arb_pl, lvr_arb_pl, fee_kept_pl, lvr_kept_pl` (per unit of full-range liquidity: Σ `fee_usd / liquidity` and Σ `lvr_0 / liquidity` over accrued steps, flash in "kept"), `fee_arb_usd, fee_arb_total_usd` (before the protocol's cut), `lvr_arb_usd, fee_kept_usd, lvr_kept_usd, fee_pips_sum, n_blocks, n_arb`.
  - `CfRun.counts` adds `arb_trades, below_min_profit, no_reference_blocks`.
  - `checks.replaced_keys(aligned: pl.DataFrame, tx_other_logs: pl.DataFrame) -> set[tuple[int, int]]`: swaps with `flow_label == "searcher"` and `other_logs == 0` (a swap without an other-logs row is kept).
  - `checks.sandwich_legs(aligned: pl.DataFrame, replaced: set[tuple[int, int]]) -> dict[str, float]`: `legs, gross_usd, notional_share, non_top_legs, non_top_gross_usd` (pattern: same `sender`, same block, opposite `zero_for_one`, another sender's swap between them).
  - `checks.min_profit_gas(aligned: pl.DataFrame, replaced: set[tuple[int, int]], end_us: int) -> int`: median `receipt_gas_used` over the distinct July transactions of replaced swaps.
  - `checks.check_s3(model: CfRun, swap_steps: pl.DataFrame, aligned: pl.DataFrame, swap_fees: pl.DataFrame, replaced: set[tuple[int, int]], sensitivity: CfRun) -> CheckResult` (name `"S3 calibration (July)"`; reported, not gated).

Simulated arbitrage at each block start (spec 6.1, 6.3), when `replace`: `p_ref` = `p_ref_0` or
`p_ref_1` by `ref_offset_s`; no reference → no trade, counted. `arb_to_price(book, p_ref, fee_pips,
ARB_CEX_FEE_BP)`; trade only if `profit_usd > base_fee_wei × min_profit_gas / 1e18 × p_ref`,
else count `below_min_profit`. A trade re-runs as `swap(book, zero_for_one, r.amount_in,
fee_pips=fee_pips)` (exact input, no limit: `ArbResult` carries no limit price) to get its steps
(source `"arb"`); assert its `amount_out` equals `r.amount_out` (the same swap from the same
state, so it lands where `arb_to_price` said). Steps are valued for LVR at `p_ref_0` (the headline t0 price,
also in the +1 s run: only the arbitrage's decision price moves).

- [ ] **Step 1: Write the failing tests:**
  - `test_fee_rules`: `VolatilityFee(2, 25)` charges `bp_to_pips(MIN_FEE_BP)` on the first block; after `end_block` calls with returns of exactly 3 bp per block for 2,000 blocks, it charges `bp_to_pips(6)` ± 1 pip; `MoveFee(1)` after a 7 bp move charges `bp_to_pips(12)`; `OracleFee` at a 20 bp basis charges `bp_to_pips(20)` and at 2 bp charges `bp_to_pips(5)`; any rule asked for 500 bp returns `bp_to_pips(100)`; `len(rule_grid()) == 24` with unique names.
  - `test_arbitrage_closes_the_gap`: a toy book with the pool 30 bp under `p_ref`, `replace=True`, `FixedFee(500)`, `min_profit_gas=0`: after the block the pool price is within the band `p_ref × (1 − 0.0005) × (1 − 0.0001)` (to 1e-9) and `daily.n_arb == 1`; the same with a huge `min_profit_gas` makes no trade and counts `below_min_profit == 1`.
  - `test_replaced_swaps_are_skipped_and_counted`: a world block with one replaced and one kept swap: the replaced one produces no `"kept"` step, the kept one does; `fee_arb_pl + fee_kept_pl` equals Σ `fee_usd/liquidity` over all accrued steps.
  - `test_daily_is_zero_filled` (Review Focus 3): a window day without events has a row of zeros.
  - `test_s3_pass_and_fail`: hand-built `CfRun`s at 1.10 and 1.20 × measured LVR → pass and fail at `CALIBRATION_TOL`; the summary carries `lvr_ratio, fee_ratio` for the model and the +1 s sensitivity.
  - `test_sandwich_pattern`: three swaps in one block, sender A buy, sender B, sender A sell → 2 legs; A buy, A sell with nothing between → 0.
- [ ] **Step 2: Run:** `uv run pytest tests/test_strategy_cfpool.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the three rules, `rule_grid`, the arbitrage in `run_pool`, the per-day aggregates, `replaced_keys`, `sandwich_legs`, `min_profit_gas`, `check_s3`.
- [ ] **Step 4: Run:** `uv run pytest -q`. Expected: all PASS.
- [ ] **Step 5: Measure runtime and memory on real data** (a throwaway script in the scratchpad, not committed): `prepare_inputs` on the real files cut to 2026-07-01 (one day), `run_pool(..., FixedFee(500), replace=True, min_profit_gas=<July median>)`; record wall time per day and the process's peak memory (`tracemalloc` for Python objects, and the working set from PowerShell `Get-Process`; `psutil` is not a dependency). Extrapolate to 92 days × 34 runs and put the numbers in the task report. Choose the default `workers` for Task 9 so that `workers × peak memory` stays under 70% of the machine's RAM (`Get-CimInstance Win32_ComputerSystem`), and state the expected wall time of a full `ulpe strategy` report run. If one full-window run would take more than about 30 minutes, report it before Task 9 starts; do not optimise speculatively.
- [ ] **Step 6: Commit** `git commit -m "strategy: simulated arbitrage, on-chain dynamic fees and the oracle bound, per-day aggregates, S3, sandwich count"`.

---

### Task 4: Range attribution and check S1

**Files:**
- Create: `src/uniswap_lp_economics/strategy/ranges.py`
- Modify: `src/uniswap_lp_economics/strategy/checks.py`
- Test: `tests/test_strategy_ranges.py`

**Interfaces:**
- Consumes: `CF_STEP_SCHEMA` steps (Task 2), `v3math.get_sqrt_ratio_at_tick`, `config.DECIMALS0/1`.
- Produces:
  - `ranges.attribute(steps: pl.DataFrame, held: pl.DataFrame) -> pl.DataFrame`: `held` has `seg, start_block, start_log, end_block, end_log, tick_lower, tick_upper, liquidity` (float; the position's liquidity over `[(start_block, start_log), (end_block, end_log))` in `(block, log_index)` order); returns per attributed step `seg, block_number, log_index, step, day, fee_usd, lvr_0, share` (`share` = ℓ / L of that step).
  - `checks.check_s1(steps: pl.DataFrame, positions: pl.DataFrame, position_flows: pl.DataFrame, snapshot_block: int) -> CheckResult` (name `"S1 range attribution vs engine"`).

`attribute` (spec 5.1), with the step's interval `[lo_s, hi_s]` = sorted `(sqrt_start, sqrt_end)`
and the range's `[pa, pb]` = `get_sqrt_ratio_at_tick` of its ticks, compared **as integers**:
- `lo_s == hi_s` (flash, or a step that does not move): in range iff `tick_lower <= tick_start <
  tick_upper`; contributes `ℓ × fee_usd / L` and `ℓ × lvr_0 / L` (Review Focus 1).
- `pa <= lo_s and hi_s <= pb`: fully inside; the step's recorded `fee_usd` and `lvr_0`, scaled by
  `ℓ / L` (so real positions reproduce the engine to float noise).
- no overlap (`hi_s <= pa or pb <= lo_s`): nothing.
- partial: overlap `[x, y]` = `[max(lo_s, pa), min(hi_s, pb)]` as floats `/ 2**96`; per unit of
  liquidity `usdc = (1/x − 1/y) / 10**DECIMALS0`, `eth = (y − x) / 10**DECIMALS1`; the input token is
  USDC when `zero_for_one`, else WETH; `fee = fee_usd × ℓ/L × in_overlap / in_step`, where
  `in_step` is the same unit formula over `[lo_s, hi_s]`; `lvr_0 = ℓ × (eth × p0 − usdc)` when
  `zero_for_one`, `ℓ × (usdc − eth × p0)` otherwise, with the step's `p0` column.
- Steps with `accrued == False` (no active liquidity) contribute nothing.

S1 (spec 5.2): for every window-active position in `positions.parquet`, its `held` rows come
from `position_flows.parquet` (cumulative `liquidity_delta` in `(block_number, pool_log_index)`
order from the start of history; one row per constant-liquidity stretch inside the window); the
sum of `attribute(...)` per position must equal `positions.fee_usd` and `positions.lvr_0` within
`S1_REL_TOL × max(1, |engine|)` per position and on the window totals. Summary: `positions,
max_rel_error_fee, max_rel_error_lvr, failures, worst_position`. If S1 fails on the real data only
by float noise, **stop and report**; do not widen the tolerance (it is pre-registered).

- [ ] **Step 1: Write the failing tests:**
  - `test_partial_step_matches_a_split_swap`: on a toy book, run one large zero-for-one exact-input swap with `v3swap.swap`; separately, add a tiny position (liquidity `L / 10**9`) at ticks strictly inside the swap's path and run the same swap: the tiny position's fees and LVR from the split run (its share of the steps between its ticks) equal `attribute` on the unsplit run's steps within relative 1e-6 (the tiny liquidity moves the price a little).
  - `test_full_inside_uses_recorded_values`: a step fully inside returns exactly `fee_usd × ℓ/L`.
  - `test_flash_at_bounds` (Review Focus 1): a flash step with `tick_start == tick_lower` is attributed; with `tick_start == tick_upper` it is not.
  - `test_s1_on_the_world`: on the lpworld, the identity replay's steps (Task 2) and the ledger's accounts (`tests/lpworld.oracle`) → `check_s1` passes; perturbing one position's `fee_usd` by 1e-6 relative makes it fail.
- [ ] **Step 2: Run:** `uv run pytest tests/test_strategy_ranges.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `attribute` (vectorized in polars; join steps to `held` by block intervals with `join_asof` on a `(block_number, log_index)` key), `check_s1`.
- [ ] **Step 4: Run:** `uv run pytest -q`. Expected: all PASS.
- [ ] **Step 5: Commit** `git commit -m "strategy: per-step range attribution, check S1 against the engine"`.

---

### Task 5: Strategy segments, scoring and costs

**Files:**
- Modify: `src/uniswap_lp_economics/strategy/ranges.py`
- Test: `tests/test_strategy_ranges.py`

**Interfaces:**
- Consumes: `attribute` (Task 4), `params`, `lp.analyze.hourly_grid`.
- Produces:
  - `ranges.range_ticks(center_tick: int, half_width_bp: int | None) -> tuple[int, int]`: `None` = full range (`-887270, 887270`); else `floor((c − w)/10)·10, ceil((c + w)/10)·10` (one tick ≈ 1 bp; `+10` on the upper if equal) *(plan's call: ticks, not exact log-bp)*.
  - `ranges.segments(rule: str, half_width_bp: int | None, starts: pl.DataFrame, start_block: int, end_block: int) -> pl.DataFrame`: `starts` = block-start states (`block_number, ts_us, day, tick, sqrt_price_x96, p_ref_0`); returns `seg, start_block, end_block, center_tick, tick_lower, tick_upper`. Re-centring decisions on each block-start tick (spec 5.3): `out_of_range` if `tick < lo or tick >= hi`; `band` if `|tick − center| > w / 2`; `daily` at the first block of each UTC day after the first; `static` and full range never. The new centre is that block's start tick.
  - `ranges.LpCosts` (dataclass): `gas_mint: int, gas_burn_collect: int, priority_wei: int` (window medians: NPM mint transactions, NPM burn+collect transactions, and `receipt_effective_gas_price − base_fee` over both); `ranges.lp_costs(events: pl.DataFrame, blocks: pl.DataFrame) -> LpCosts`.
  - `ranges.score(steps: pl.DataFrame, segs: pl.DataFrame, starts: pl.DataFrame, grid: pl.DataFrame, capital: float, costs: LpCosts, taker_fee_bp: float, days: list[date]) -> StrategyResult`.
  - `ranges.StrategyResult` (dataclass): `daily: pl.DataFrame` (`day, fee_usd, lvr_usd, gas_usd, trade_usd, twv_usd, in_range_blocks, n_blocks, recentres`, one row per day in `days`, zero-filled), `peak_ratio: float` (max ℓ/L over attributed steps), `segs: pl.DataFrame` (with `liquidity`, `eth_start`), `bp_per_day: float`.
  - `ranges.peak_share(peak_ratio: float, scale: float = 1.0) -> float` = `r·scale / (1 + r·scale)`.
  - `ranges.STRATEGY_COLUMNS`: the per-cell table `strategy, rule, half_width_bp, capital, fees_over_lvr, bp_per_day, recentres, gas_usd, trade_usd, in_range_share, days_in_range, peak_share, flagged, counted`.

Scoring (spec 5.3): first segment ℓ = `capital / v_unit` at the period's first block start
(`v_unit` per unit liquidity at `sqrt, p_ref_0` as in `pnl.time_weighted_value`); at each
re-centring, the new ℓ makes the new position's value equal the old one's at that block start.
Costs are paid from cash, so ℓ scales with capital: score at `PRIMARY_CAPITAL` and derive $100k by
scaling fees, LVR, trade cost and twv by 0.1 with gas unchanged. Per re-centring: gas `(gas_burn_collect
+ gas_mint) × (base_fee + priority_wei) / 1e18 × p_ref_0`; trade `|eth_new − eth_old| × p_ref_0 ×
taker_fee_bp / 1e4`. `twv_usd` per day = mean of that day's hourly position values (the grid's
`sqrt` and `p_cex`). `bp_per_day = Σ(fee − lvr − gas − trade) / Σ twv × 1e4`.

- [ ] **Step 1: Write the failing tests:**
  - `test_range_ticks`: `range_ticks(201_003, 100) == (200_900, 201_110)`; `range_ticks(5, None) == (-887270, 887270)`.
  - `test_rules`: a synthetic `starts` path that leaves a ±100 bp range once and crosses one midnight → `out_of_range` has 2 segments, `band` ≥ 2, `daily` 2 (the first day does not re-centre), `static` 1.
  - `test_value_is_carried_and_costs_charged`: one re-centring at an unchanged price → the new ℓ gives the old value to 1e-9; `trade_usd` = `|Δeth| × p × 5e-4`; `gas_usd` = (gas units × (base + priority)) / 1e18 × p.
  - `test_capital_scaling`: $100k derived by scaling equals a direct $100k score on fees, LVR, trade and twv (rel 1e-9); gas is the same.
  - `test_score_full_range_equals_per_liquidity`: full range at ℓ: `fee_usd` = ℓ × Σ `fee_usd/L` (the `fee_*_pl` columns of the identity run) to 1e-9.
- [ ] **Step 2: Run:** `uv run pytest tests/test_strategy_ranges.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `range_ticks`, `segments`, `LpCosts`, `lp_costs`, `score`, `peak_share`.
- [ ] **Step 4: Run:** `uv run pytest -q`. Expected: all PASS.
- [ ] **Step 5: Commit** `git commit -m "strategy: rebalancing rules, price-taker scoring, gas and re-centring trade costs"`.

---

### Task 6: Paired bootstrap and the verdicts

**Files:**
- Create: `src/uniswap_lp_economics/strategy/stats.py`
- Test: `tests/test_strategy_stats.py`

**Interfaces:**
- Consumes: `theory.N_BOOT`, `theory.SEED`, `params`.
- Produces:
  - `stats.day_index(n_days: int, n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray` (`rng.integers(0, n_days, (n_boot, n_days))`, as `theory.day_bootstrap_sum` draws).
  - `stats.on_grid(daily: pl.DataFrame, days: list[date], cols: list[str]) -> pl.DataFrame` (left join onto the day grid, zeros).
  - `stats.ratio_draws(num: np.ndarray, den: np.ndarray, idx: np.ndarray) -> np.ndarray` (per draw Σnum/Σden; `nan` where Σden ≤ 0).
  - `stats.Paired` (dataclass): `point: float, lo: float, hi: float, n_undefined: int, inside: bool, above: bool, below: bool`.
  - `stats.paired(a: np.ndarray, b: np.ndarray, point: float, delta: float) -> Paired` (draws of a − b; `nan` if either is `nan`).
  - `stats.delta_from(r0: float) -> float` = `(1 − r0) / DELTA_DIVISOR`; raises `ValueError("full range broke even in July (r0 = …): the pre-registered margin is undefined")` if `r0 >= 1`.
  - `stats.range_verdict(cells: dict[str, Paired]) -> str` (`"holds" | "fails" | "inconclusive"`).
  - `stats.fee_verdicts(levels: dict[float, Paired], calibrated: bool, baseline_bp: float = BASELINE_FEE_BP) -> tuple[dict[float, str], str]` (per level: `"holds" | "fails" | "inconclusive"` for f > baseline, `"not tested (below baseline)"` for f < baseline, the baseline itself left out; summary `"holds from <f> bp" | "fails" | "not tested (calibration failed)"`, judged on levels above the baseline only; spec 7.2).
  - `stats.break_even_share(r_f: float, r_5: float, fees_kept_f: float, lvr_kept_f: float) -> float | None` (spec 6.5; `None` if the denominator ≤ 0).
  - `stats.break_even_fee(fees_bp: list[float], ratios: list[float]) -> float | None` (lowest fee where the ratio reaches 1, linear between grid points; `None` if never).
  - `stats.interp(xs: list[float], ys: list[float], x: float) -> float`.
  - `stats.protocol_cut(fees_lp: float, cut: float) -> float` = `fees_lp × (1 − cut) / (1 − 0.25)`; `PROTOCOL_CUTS = (0.0, 0.1, 0.25)`.

Interval and decision rules (spec 7), not left to judgement:
- `lo, hi` = 2.5th and 97.5th percentiles of the **defined** draws (`np.nanpercentile`).
- `inside` = `n_undefined / n_boot <= UNDEFINED_MAX_SHARE` and the 2.5th and 97.5th percentiles
  of **all** draws with `nan` replaced by `+inf` (`np.percentile(..., method="inverted_cdf")`) lie
  in `[−δ, +δ]`.
- `above` = `lo > δ` on defined draws; `below` = `hi < δ` on defined draws.
- Range: `"fails"` if any counted cell is `above`; else `"holds"` if every one is `inside`; else
  `"inconclusive"`.
- Fee level (f > 5 bp only; lower levels are `"not tested (below baseline)"`): `"holds"` if
  `above`, `"fails"` if `below`, else `"inconclusive"`; summary is the lowest level above 5 bp
  that holds, `"fails"` if none does.

- [ ] **Step 1: Write the failing tests:**
  - `test_index_matches_theory`: `day_index(61)[0]` equals the first row `theory.day_bootstrap_sum` would draw (same rng call).
  - `test_on_grid_zero_fills` (Review Focus 3): a frame missing a day gets a zero row in grid order.
  - `test_undefined_draws` (Review Focus 4): with 3% of draws `nan`, `inside is False` even when the defined draws sit at 0; with 2% `nan` at 0 and δ = 0.07, `inside is True`; `nan` draws never make `above` true.
  - `test_verdicts`: three cells inside → `"holds"`; one above → `"fails"`; one straddling → `"inconclusive"`; fee levels `{1: below +δ, 10: inconclusive, 20: holds, 30: holds}` → level 1 is `"not tested (below baseline)"` and the summary is `"holds from 20 bp"` (level 1 lying below +δ does not make anything `"fails"`); `calibrated=False` → `"not tested (calibration failed)"`.
  - `test_delta`: `delta_from(0.72) == 0.07`; `delta_from(1.0)` raises.
  - `test_break_even`: `break_even_fee([5, 10, 20], [0.8, 0.9, 1.1]) == 15.0`; `break_even_share(1.0, 0.0, 4.0, 2.0) == 0.5`; denominator 0 → `None`; `protocol_cut(75.0, 0.0) == 100.0`.
- [ ] **Step 2: Run:** `uv run pytest tests/test_strategy_stats.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `stats.py`.
- [ ] **Step 4: Run:** `uv run pytest tests/test_strategy_stats.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "strategy: paired day bootstrap, pre-registered verdicts, break-even"`.

---

### Task 7: Binance futures data (`ulpe fetch-futures`)

**Files:**
- Create: `src/uniswap_lp_economics/data/futures.py`
- Modify: `src/uniswap_lp_economics/cli.py` (subcommand and `ALL_STEPS` entry before `"lp"`)
- Test: `tests/test_futures.py`

**Interfaces:**
- Consumes: `binance.download_verified(url, dest, client)`, `binance._read_zip_csv` pattern.
- Produces:
  - `futures.BASE = "https://data.binance.vision/data/futures/um/monthly"`; `futures.FUTURES_DIR = "binance_futures"`.
  - `futures.funding_url(symbol: str, year: int, month: int) -> str` (`…/fundingRate/{s}/{s}-fundingRate-{y}-{m:02d}.zip`); `futures.klines_url(symbol, interval, year, month) -> str` (`…/klines/{s}/{i}/{s}-{i}-{y}-{m:02d}.zip`).
  - `futures.fetch_futures(months: list[tuple[int, int]], raw_dir: Path, symbol: str = HEDGE_SYMBOL) -> list[Path]` (skips files already on disk).
  - `futures.load_funding(raw_dir: Path) -> pl.DataFrame` (`ts_us, rate`), `futures.load_perp_minutes(raw_dir: Path) -> pl.DataFrame` (`ts_us` = minute open, `close`).
  - CLI: `ulpe fetch-futures` (months 2026-07..09); `run_step("fetch-futures")`.

- [ ] **Step 1: Download one real file of each kind** (`curl -sO` the July funding and klines zips into the scratchpad) and read their CSV headers; pin them in `futures.py` as `FUNDING_COLS` and reuse `binance.KLINE_COLS` if identical (futures klines may carry a header row; skip it if present).
- [ ] **Step 2: Write the failing tests:** `test_urls` (exact strings for 2026-07); `test_parse_funding` and `test_parse_klines` on zips built in the test from the pinned headers (with and without a header row); `test_fetch_skips_existing` (a stub client is never called when the file exists).
- [ ] **Step 3: Run:** `uv run pytest tests/test_futures.py -q`. Expected: FAIL.
- [ ] **Step 4: Implement** `futures.py` and the CLI wiring.
- [ ] **Step 5: Run:** `uv run pytest -q`. Expected: all PASS.
- [ ] **Step 6: Fetch for real:** `uv run ulpe fetch-futures`; expected: 6 files under `data/raw/binance_futures/`, checksums verified.
- [ ] **Step 7: Commit** `git commit -m "data: Binance USD-M ETHUSDC funding and 1-minute klines (ulpe fetch-futures)"`.

---

### Task 8: The hedge

**Files:**
- Create: `src/uniswap_lp_economics/strategy/hedge.py`
- Test: `tests/test_strategy_hedge.py`

**Interfaces:**
- Consumes: `StrategyResult.segs` (Task 5), futures frames (Task 7), block-start states.
- Produces:
  - `hedge.position_path(segs: pl.DataFrame, starts: pl.DataFrame, minutes: pl.DataFrame) -> pl.DataFrame` (`ts_us, eth, value_usd`: the position's WETH amount and token value at spot, per minute, as-of the block-start pool price).
  - `hedge.simulate(path: pl.DataFrame, perp: pl.DataFrame, funding: pl.DataFrame, rule: str, taker_fee_bp: float) -> pl.DataFrame` (per day: `day, hedge_pnl_usd, funding_usd, trade_usd, rehedges`).
  - `hedge.hedge_table(lp_daily: pl.DataFrame, path: pl.DataFrame, perp: pl.DataFrame, funding: pl.DataFrame, capital: float) -> pl.DataFrame` (`strategy, rule, taker_fee_bp, bp_per_day, sd_daily_usd_per_1m, mean_daily_usd_per_1m`, plus a `rebalancing_benchmark` row; the `never` rule is the unhedged position, listed once with taker fee 0).

Rules (spec 8): hedge `h` = short `eth` perp contracts, re-set to the current `eth` at: `never` (h = 0),
`daily` (first minute of each UTC day), `hourly`, `drift` (any minute where `|eth − h| × close >
HEDGE_DRIFT × value_usd`); the first minute of the period sets `h` for every rule but `never`.
Hedge P&L per minute `−h × Δclose`; funding at each funding time `+h × close × rate` (a short
receives positive funding); trade cost `|Δh| × close × taker_fee_bp / 1e4`. Daily LP USD P&L =
`value_usd` change + `fee_usd − gas_usd − trade_usd` from the strategy's daily frame (the LP is
valued at Binance spot and the hedge at the perp close, so the perp–spot basis is in the hedge's
P&L by construction);
`rebalancing_benchmark` = `fee_usd − lvr_usd − gas_usd − trade_usd`. The README states the identity:
the hedge changes the spread, not fees − LVR.

- [ ] **Step 1: Write the failing tests:** `test_never_has_no_cost`; `test_hourly_on_a_linear_path`: with `eth` constant and the perp rising $1 per minute for 120 minutes, `hourly` has hedge P&L `−eth × 120` and 2 re-hedges after the first; `test_funding_sign`: a positive rate pays the short; `test_drift_rule` re-hedges only past 10%; `test_table_rows`: per strategy, `never` once + 3 rules × 3 taker fees + `rebalancing_benchmark` = 11 rows, and no row named `unhedged`.
- [ ] **Step 2: Run:** `uv run pytest tests/test_strategy_hedge.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `hedge.py`.
- [ ] **Step 4: Run:** same. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "strategy: perp delta hedge rules with funding, basis and taker fees"`.

---

### Task 9: `ulpe strategy`: gates, July, freeze, August–September, outputs

**Files:**
- Create: `src/uniswap_lp_economics/strategy/analyze.py`
- Modify: `src/uniswap_lp_economics/cli.py` (`strategy` subcommand; `ALL_STEPS`: `"fetch-futures"` before `"lp"`, `"strategy"` after `"lp"`, before `"figures"`)
- Test: `tests/test_strategy_analyze.py`, `tests/test_cli_all.py` (existing; update the step list)

**Interfaces:**
- Consumes: everything above; `lp.analyze.load_lp_inputs`, `lp.analyze.hourly_grid`, `validate.require_validated`, `validate.file_hash`, `validate.git_commit`, `report.write_markdown/write_table/metrics_table`, `io.write_text_atomic`.
- Produces:
  - `analyze.PREREG_TAG = "strategy-preregistered"`.
  - `analyze.FREEZE_FILE = "strategy_freeze.json"` (in `results/`).
  - `analyze.write_freeze(path: Path, payload: dict[str, Any]) -> None` (refuses with `FileExistsError` if the file exists; writes atomically).
  - `analyze.read_freeze(path: Path, hashes: dict[str, str]) -> dict[str, Any]` (raises `SystemExit` with a message naming the file if it cannot be parsed or its `input_hashes` differ from `hashes`; never writes).
  - `analyze.strategy_analysis(inp: LpInputs, extra: StrategyExtras, results_dir: Path, processed_dir: Path, provenance: dict[str, Any], split_us: int = REPORT_START_US, end_us: int | None = None, workers: int | None = None) -> str` (`"PASS"`/`"FAIL"`).
  - `analyze.StrategyExtras` (dataclass): `positions, position_flows, swap_steps: pl.DataFrame; funding, perp: pl.DataFrame`.
  - `analyze.run_strategy() -> str` (refuses unless `results/summary.json` has `"lp"` and the processed LP files exist).

Flow of `strategy_analysis` (spec 4, 9), in **two runs** (spec 4: "the first run computes July
only and writes the freeze"). With no freeze file, the run does steps 1, 3 (July only) and 4,
writes the freeze and `strategy_checks.md`, prints `July frozen: commit results/strategy_freeze.json,
tag it strategy-preregistered, then run ulpe strategy again`, and returns `"FROZEN"`, having
computed no report-period number (its cfpool runs use `prepare_inputs(..., end_us=split_us)`).
With a freeze file, it does steps 1, 2, 3 (report period), 5 and 6, taking every July value from
the freeze.
1. `replaced = replaced_keys(...)`; `ci = prepare_inputs(...)`; identity run `run_pool(ci, FixedFee(500), replace=False, keep_steps=True)`; `check_s2`; `check_s1` on its steps. Either fails → write `strategy_checks.md` (via `validate.write_report(..., stem="strategy_checks", title="Strategy checks")`) and return `"FAIL"`, no other file written.
2. (Report run.) Fee runs, in a `concurrent.futures.ProcessPoolExecutor` (`workers` default `os.cpu_count() − 1`; the worker initializer receives `ci` once; Windows spawns processes, so the worker function and the rules must be top-level and picklable; `workers=1` runs in-process, which the tests use): every rule in `rule_grid()` with `replace=True, ref_offset_s=0`, plus the 10 fixed levels at `ref_offset_s=1`. Each run covers the whole window from the snapshot (the counterfactual pool is carried through July into August, *plan's call*); `daily` is split by period afterwards.
3. Range cells on the identity steps, with `starts` = `blocks_state` (`block_number, ts_us, tick, sqrt_price_x96`) joined to `ci.blocks` (`day, p_ref_0`): for the run's period (July in the first run, the report period in the second), fresh capital at the period's first block (spec 4): 9 widths × 4 rules + full range, `score` at `PRIMARY_CAPITAL` and taker fee 5 bp; the 1 and 10 bp taker variants re-price `trade_usd` linearly.
4. **July (first run only):** `min_profit_gas = checks.min_profit_gas(...)` on July; `r0` = July full-range fees ÷ LVR; `delta = delta_from(r0)`; S3 on July (two 5 bp runs on the July-cut `ci`, the model and its +1 s variant, both with that `min_profit_gas`); best strategy = the tested cell (rule in `TESTED_RULES`) with the highest July `bp_per_day` at $1M. `write_freeze` with `delta, r0, min_profit_gas, calibration (passed, ratios), best_strategy, cfpool_counts` (both July runs) `, input_hashes` (`validate.file_hash` of every input file the strategy step reads, keyed by data-relative path), `git_commit, generated_utc`. In the report run, `read_freeze` (Review Focus 5) supplies `delta`, `min_profit_gas`, the calibration verdict and the best strategy; July is not recomputed.
5. **Report period** (report run) with the frozen values: range test (27 tested cells at $1M, `paired` against full range on `ratio_draws` of daily fees and LVR; static cells descriptive with `in_range_share`, `days_in_range`), size flags (`peak_share > PEAK_SHARE_FLAG` at each capital), fee per-level verdicts on the arbitrage side (`fee_arb_pl / lvr_arb_pl` at f against the 5 bp model run), whole-pool ratios (`(fee_arb_pl + fee_kept_pl) / (lvr_arb_pl + lvr_kept_pl)`), `break_even_share` per configuration, `X = break_even_fee` on the fixed levels and `Y = interp(levels, shares, X)`, dynamic and oracle rows with their average charged fee (`fee_pips_sum / n_blocks / 100`), a reference row for the real pool (the identity run's ratios), the +1 s rows of the fixed levels, protocol cut rows on the real full range, the hedge table for full range and the best strategy.
6. (Report run.) Write (nothing before every number is computed, as `lp_analysis` does): `strategy_checks.md` (S1, S2, S3, size flags, sandwich count, the cfpool counts), `strategy_ranges.md/.csv` (`STRATEGY_COLUMNS`; tested and static tables separately), `strategy_fees.md/.csv`, `strategy_hedge.md/.csv`, `strategy_test.md` (δ, r0, both verdicts, the lowest holding fee, X, Y, which cells are flagged and whether a verdict depends on one); `summary.json["strategy"]` (read the existing file, replace only that key); figure data under `results/figure_data/strategy_*.csv` for Task 11. Every table carries the counterfactual note (`COUNTERFACTUAL_NOTE`, one sentence: "Counterfactual: holds other traders' behaviour fixed; they would react to a different range, fee or hedge.") and fee tables also `FEE_NOTE` naming the fixed-volume shortcut and the break-even beside it, and "model-only" if calibration failed.

- [ ] **Step 1: Write the failing tests** (on lpworld inputs with a `split_us` inside the world and synthetic futures frames):
  - `test_first_run_freezes_and_stops`: with no freeze, `strategy_analysis` returns `"FROZEN"` and writes only `strategy_freeze.json` (carrying `delta, r0, min_profit_gas, calibration, best_strategy, input_hashes`) and `strategy_checks.md`: no `strategy_ranges*`, `strategy_fees*`, `strategy_hedge*`, `strategy_test.md` or `figure_data/strategy_*`, and `summary.json` byte-identical.
  - `test_second_run_writes_every_file`: a second call returns `"PASS"`, writes the six results files, leaves the freeze byte-identical, and `summary.json` keeps its `"lp"` key unchanged and gains `"strategy"`.
  - `test_failed_gate_writes_only_checks`: monkeypatch `check_s1` to fail → `"FAIL"`, `strategy_checks.md` exists, no other strategy file and no freeze.
  - `test_freeze_is_write_once` (Review Focus 5): `write_freeze` on an existing path raises `FileExistsError` and leaves it unchanged.
  - `test_freeze_mismatch_stops`: a freeze whose `input_hashes` differ, and one with invalid JSON → `SystemExit` naming the file; the file is unchanged.
  - `test_frozen_values_win`: a hand-edited frozen `delta` and `min_profit_gas` are what the report run uses (δ in `strategy_test.md`; `min_profit_gas` in every `run_pool` call).
  - `test_all_steps_order` (in `test_cli_all.py`): `"fetch-futures"` precedes `"lp"`, `"strategy"` sits between `"lp"` and `"figures"`.
- [ ] **Step 2: Run:** `uv run pytest tests/test_strategy_analyze.py tests/test_cli_all.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `analyze.py` and the CLI wiring.
- [ ] **Step 4: Run:** `uv run pytest -q`. Expected: all PASS; then CI's own commands: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`. Expected: no findings. Every later task ends with the same four commands before its commit.
- [ ] **Step 5: Commit** `git commit -m "strategy: ulpe strategy with gates S1/S2, July freeze, report-period verdicts and outputs"`.

---

### Task 10: The real run

**Files:**
- Modify: `results/` (new strategy files, `summary.json` `"strategy"` key, the freeze), nothing else.

- [ ] **Step 1: First run (July only):** `uv run ulpe strategy` in the background (`run_in_background`, log to the scratchpad). Expected: `PASS  S2 identity replay: …mismatches 0…`, `PASS  S1 range attribution vs engine: …failures 0…`, then `July frozen: …` and status `FROZEN`; `results/` gains only `strategy_freeze.json` and `strategy_checks.md`.
- [ ] **Step 2: Sanity-check July before committing anything:** `r0` within 0.05 of the builder check's 0.73 estimate; S3's `lvr_ratio` and `fee_ratio` finite and positive; the cfpool counts plausible (`arb_trades` in the tens of thousands for July, `to_price_skipped` and `no_reference_blocks` small, `below_min_profit` reported). A failure here is a bug, not a finding: delete the uncommitted freeze, fix it with superpowers:systematic-debugging, and repeat Step 1. Nothing about the report period is known yet, so this is allowed.
- [ ] **Step 3: Pre-register:** `git add results/strategy_freeze.json results/strategy_checks.md && git commit -m "strategy: July freeze (delta, r0, min_profit_gas, calibration verdict, best strategy)" && git tag strategy-preregistered && git push --follow-tags`. From here on the freeze is never edited or deleted.
- [ ] **Step 4: Report run:** `uv run ulpe strategy` again, in the background. Expected status `PASS` and the report-period files of Task 9.
- [ ] **Step 5: Read the results** (`results/strategy_test.md` first): every tested cell has an interval; the arbitrage-side fee curve rises with the level, or the deviation is explained in the task report. Whatever the verdicts are, they are reported as computed.
- [ ] **Step 6: Commit results** `git add results/ && git commit -m "Results: Phase 5 strategy experiment (range test, fee curves, hedge)"`; push the branch.

---

### Task 11: Figures 14–16

**Files:**
- Create: `src/uniswap_lp_economics/viz/strategy.py`
- Modify: `src/uniswap_lp_economics/viz/render.py` (`FIGURES` += three entries), `src/uniswap_lp_economics/viz/data.py` (load the strategy figure data into `Results`), `tests/vizfix.py` (fixture frames for them)
- Test: `tests/test_viz_strategy.py`

**Interfaces:**
- Consumes: `results/figure_data/strategy_ranges.csv`, `strategy_fees.csv`, `strategy_hedge.csv`, `summary.json["strategy"]`; house style from `viz/style.py`.
- Produces: `viz.strategy.range_test(r: Results) -> Figure` (`14_range_test`), `viz.strategy.fee_curves(r) -> Figure` (`15_fee_curves`), `viz.strategy.hedge_risk(r) -> Figure` (`16_hedge`); `viz.strategy.title_range(verdict: str, delta: float) -> str` and `title_fee(x_bp: float | None, y_share: float | None, model_only: bool) -> str` (claim titles only when the data support them, as `viz.robustness.title`).

Figure content (spec 9): (14) Δ(fees ÷ LVR) with paired intervals per tested cell, widths on the
x axis, one marker style per rule, the ±δ band shaded; static cells not drawn. (15) two panels:
arbitrage-side fees ÷ LVR against fee level with +δ above the 5 bp value marked and the dynamic
points at their average fee; break-even volume loss against fee level, with whole-pool fees ÷ LVR
and X marked. (16) hedge: mean daily return against the SD of daily P&L per rule (`never` is the
unhedged position) and the rebalancing benchmark marked. Every figure's source note carries the counterfactual caveat;
figure 15 says "model-only" when calibration failed.

- [ ] **Step 1: Write the failing tests:** titles: `title_range("holds", 0.068)` starts `"No range or rebalancing rule moves fees ÷ LVR by more than 0.07"`; `"fails"` and `"inconclusive"` give titles that claim nothing beyond the verdict; `title_fee(18.0, 0.31, False)` contains `"about 18 bp"` and `"31%"`; `title_fee(..., True)` starts `"Model only:"`; each figure renders from `vizfix` and its source text contains `"ignores how other traders would react"`; render is byte-stable twice (as the other figure tests).
- [ ] **Step 2: Run:** `uv run pytest tests/test_viz_strategy.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the three figures and the registry entries.
- [ ] **Step 4: Run** `uv run pytest -q` and `uv run ulpe figures`; look at the three SVGs (preview PNGs) before committing.
- [ ] **Step 5: Commit** `git commit -m "Figures 14-16: range test, fee curves, hedge risk"`.

---

### Task 12: README chapter, methodology section 21, roadmap

**Files:**
- Modify: `README.md`, `docs/methodology.md`, `docs/roadmap.md`

- [ ] **Step 1: README.** Status line (Phase 5 done); TL;DR item 7, findings first: the range verdict, the fee curve's X and Y, the hedge's spread change, each with its counterfactual caveat beside it; contents entry; chapter "Can an LP do better?" after "Is it the reference price?": the argument of spec 1 (which levers cannot work and why), the pre-registration (July choices, frozen δ, August–September report, the freeze commit), the range table and figure 14, the fee curves and figure 15 with "LPs break even at about X bp, and at that fee the pool can lose at most Y% of its other volume", the dynamic and oracle rows (the oracle as an upper bound), the protocol cut as arithmetic, the hedge table and figure 16 with the identity stated, JIT's exclusion in one line; Limitations subsection "Strategy experiment (Phase 5)": price-takers (flagged cells), no routing and the fixed-volume shortcut, the arbitrage always first in the block, the L1 mode ambiguity, the sandwich share, multi-pool searcher swaps kept, the ETHUSDC perp, and the honesty note that the window's aggregates were known when the hypothesis was written; Reproduce (`fetch-futures`, `strategy`); repo map (`strategy/`, `data/futures.py`).
- [ ] **Step 2: Methodology section 21** (after section 20): definitions and formulas of spec 5–8 as built (attribution cases, segments, costs, cfpool order, fee rules with their grids, S1–S3, the paired bootstrap and decision rules, break-even, hedge), and the departures from the spec, if any, each with its reason.
- [ ] **Step 3: Roadmap:** Phase 5 into the Done table with spec and plan links and a one-line answer; "Later" keeps Phase 6.
- [ ] **Step 4: Check** every number in the new README text against `results/strategy_*.md` and `summary.json` (grep each one), and `grep -riE "tox[i]city" README.md docs/` returns nothing.
- [ ] **Step 5: Commit** `git commit -m "Docs: Phase 5 strategy experiment (README chapter, methodology section 21, roadmap)"`; push; merge `strategy-experiment` into `main` with a merge commit named like the earlier ones; push `main`.
