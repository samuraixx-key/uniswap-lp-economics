# Reference and Timing Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show how far LP fees − LVR (−$1.06M) moves under other reference prices and other t0
offsets, measure when blocks are actually sealed, and draw it as figure 13 with a README chapter.

**Architecture:** `ulpe lp` gains a robustness table: every cell is the headline plus a per-swap
shift `X(P_cell) − X(P_primary)` from the L6 identity, summed by day, so the primary 0 s cell is
the headline by construction and a paired day bootstrap reuses `theory.day_bootstrap_sum`'s draws.
A new free fetch step, `fetch-timing`, records winning-bid times from the relays that keep
history. `ulpe figures` draws figure 13 from the new results files only.

**Tech Stack:** Python 3.13, polars, numpy, httpx (MockTransport in tests), matplotlib, pytest,
ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-10-21-reference-robustness-design.md`

## Global Constraints

- 0 s at the Binance last trade stays the headline everywhere; the measured t0 is reported next to
  it, never swapped in.
- The timing band is drawn as observed, and everywhere it appears says it covers only blocks
  delivered through Titan, Flashbots and Aestus, and that ultrasound (the largest relay) keeps no
  bid history for this window.
- Every number in figure 13's title and subtitle comes from `results/`; titles fall back to a
  neutral statement when the data contradicts the claim.
- No paid query and no new bulk download. Relay calls are free; reuse `relays._get`'s retries and
  `RelayBreaker`.
- Never read `.env`; never print or log the RPC URL. Never use the word "toxicity".
- Renders stay byte-deterministic; `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy src` and `uv run pytest -q` stay clean.
- Commits carry no AI attribution lines. Work on branch `reference-robustness`; merge to `main`
  only after the final review and the user's OK.

## Rulings made while planning (deviations from the spec)

1. **Figure 12's label item is dropped.** The note predates the chart redesign; the current
   figure 8 (bots, the chart with a negative "kept" bar) was rendered on 2026-10-21 and its
   −$192k label sits clear below the bar. Spec section 8 and the roadmap lose that bullet.
2. **Cells are computed as shifts from the headline** (Task 4), not as independent totals. This
   makes the primary 0 s cell equal `summary.json` exactly and handles the 57 flash loans with no
   special case. R6 (spec 9) therefore checks the identity itself: the primary 0 s identity total
   plus the flash-loan LP fees equals the headline fees − LVR within `L6_REL_TOL` relative (not
   "to the cent": float sums over 534k swaps).
3. **A swap with no price in a cell** (offset past the window end, or the mid proxy before both
   sides have traded) gets a zero shift and is counted in `n_unpriced` for that cell.
4. **Timing sample:** the existing 1,000 relay-sample blocks (`relays.sample_blocks`, seed 42),
   each tried on Titan, Flashbots and Aestus in that order. If fewer than 150 are timed, a second
   batch of 1,000 (seed 43) is tried. A block's winning bid is the earliest `timestamp_ms` among
   the relay's received bids whose `block_hash` equals the delivered one.
5. **`ulpe all` builds positions once:** `fetch_chain_state` skips `build_positions` when the
   start-positions, end-positions and owner-code files all exist. (The second build is the one
   `ulpe lp` needs.)

## Review Focus

1. Prices missing at the window edges (t0 + 4 s past the window end; the mid proxy at the very
   start) must not drop swaps or produce NaN totals: zero shift, counted (Task 4 test).
2. A day present in `lvr_daily` with no swaps, or a swap day absent from it, must line up by day
   with zeros, not misalign the bootstrap (Task 4 test).
3. A relay that delivered a block but whose bid list no longer holds the winning hash, or returns
   `timestamp_ms` as a string, must give a not-found row, not a crash (Task 5 tests).
4. A curve that never crosses zero, or crosses after 0 s or inside the timing band, must change
   the title, not keep the "unless read N s before" claim (Task 7 test).
5. Zero timed blocks must still render figure 13 (no band, the caption says so) and keep
   `summary.json` valid (Task 7 test).

---

### Task 1: Carried-over check fixes (A5, A6, L1)

**Files:**
- Modify: `src/uniswap_lp_economics/checks.py` (`check_a5`, `check_a6`)
- Modify: `src/uniswap_lp_economics/lp/checks.py:17-38` (`check_l1`)
- Test: `tests/test_checks.py`, `tests/test_lp_analyze.py`

**Interfaces:**
- Produces: `check_l1(swap_fees: pl.DataFrame, engine_unmatched: int) -> CheckResult` (no default).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_checks.py
def test_a5_and_a6_are_reported_not_gated(labelled, transfers, aligned, blocks) -> None:
    assert check_a5(labelled).reported and check_a6(transfers, aligned, blocks).reported

# tests/test_lp_analyze.py
def test_l1_by_mode_is_sorted_and_engine_count_is_required() -> None:
    fees = pl.DataFrame({"mode": ["exact_output", "exact_input", "exact_input"], ...})
    assert list(check_l1(fees, 0).details["by_mode"]) == ["exact_input", "exact_output"]
    with pytest.raises(TypeError):
        check_l1(fees)  # type: ignore[call-arg]
```

Build the inputs from the existing fixtures in each file (both files already construct A5/A6 and
L1 inputs; reuse them). Use whatever attribute `CheckResult` exposes for the summary dict.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_checks.py tests/test_lp_analyze.py -q -k "reported_not_gated or by_mode_is_sorted"`
Expected: FAIL (`reported` is False; dict order follows the data; the call without a count works).

- [ ] **Step 3: Implement**

`reported=True` on A5 and A6; in `check_l1` sort `counts` by mode name; drop the default. Fix
every caller that relied on the default (grep `check_l1(`).

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "Checks: A5/A6 reported, L1 by_mode sorted, check_l1 needs the engine count"
```

### Task 2: `ulpe all` builds positions once

**Files:**
- Modify: `src/uniswap_lp_economics/cli.py:154-191` (`fetch_chain_state`)
- Test: `tests/test_cli_all.py`

- [ ] **Step 1: Write the failing test**

```python
def test_chain_state_skips_the_position_build_when_everything_is_on_disk(monkeypatch, tmp_path):
    # RAW_DIR -> tmp_path with snapshot meta, both fee files, history pool file, and
    # start_positions / end_positions / owner_code present; _rpc stubbed.
    monkeypatch.setattr(cli, "build_positions", lambda *a: pytest.fail("built positions"))
    cli.fetch_chain_state()
```

- [ ] **Step 2: Run it** — Expected: FAIL with "built positions".

- [ ] **Step 3: Implement** — return before `build_positions` when
  `START_POSITIONS`, `END_POSITIONS` and `OWNER_CODE` all exist in the chain-state folder, printing
  "position state and owner code already downloaded, skipping".

- [ ] **Step 4: Run** `uv run pytest tests/test_cli_all.py -q` — Expected: pass.

- [ ] **Step 5: Commit** — `git commit -m "CLI: skip the position build in fetch-chain-state when its outputs exist"`

### Task 3: Trade-side mid reference

**Files:**
- Modify: `src/uniswap_lp_economics/align.py`
- Test: `tests/test_align.py`

**Interfaces:**
- Produces:
  - `trade_side_table(trades: pl.DataFrame) -> pl.DataFrame` with columns `ts_us, ask, bid`
    (latest buyer-initiated price as `ask`, latest seller-initiated as `bid`, forward-filled; one
    row per microsecond, the latest by `agg_trade_id`; rows before both sides exist dropped).
  - `trade_side_mid_table(trades: pl.DataFrame) -> pl.DataFrame` with `ts_us, price`
    (`(ask + bid) / 2`), usable by `reference_at`.
  - `proxy_quality(times_us: pl.Series, trades: pl.DataFrame, end_us: int) -> dict[str, float]`
    with keys `crossed_share`, `spread_bp_p10`, `spread_bp_p50`, `spread_bp_p90`,
    `mean_abs_last_minus_mid_bp`, evaluated at `times_us`.

`is_buyer_maker = False` means the buyer took liquidity, so the trade printed at the ask.

- [ ] **Step 1: Write the failing tests**

```python
def test_trade_side_mid_uses_the_latest_of_each_side() -> None:
    trades = pl.DataFrame({
        "agg_trade_id": [1, 2, 3, 4],
        "ts_us": [10, 20, 20, 30],
        "price": [100.0, 101.0, 99.0, 102.0],
        "qty": [1.0] * 4,
        "is_buyer_maker": [False, False, True, False],
    })
    t = align.trade_side_mid_table(trades)
    # ts 10: only an ask -> dropped; ts 20: ask 101 (id 2), bid 99 (id 3) -> 100; ts 30: ask 102
    assert t.to_dicts() == [{"ts_us": 20, "price": 100.0}, {"ts_us": 30, "price": 100.5}]

def test_proxy_quality_counts_crossed_sides() -> None:
    # ask 99 below bid 100 at the query time -> crossed_share 1.0, spread_bp_p50 < 0
    ...
```

- [ ] **Step 2: Run** `uv run pytest tests/test_align.py -q` — Expected: FAIL (names undefined).
- [ ] **Step 3: Implement** the three functions in `align.py`.
- [ ] **Step 4: Run** — Expected: pass.
- [ ] **Step 5: Commit** — `git commit -m "Align: trade-side bid/ask proxy and its quality numbers"`

### Task 4: The robustness table and paired bootstrap

**Files:**
- Create: `src/uniswap_lp_economics/lp/robustness.py`
- Test: `tests/test_robustness.py`

**Interfaces:**
- Consumes: `align.reference_at`, `align.reference_table`, `align.kline_reference_table`,
  `align.trade_side_mid_table` (Task 3), `theory.N_BOOT`, `theory.SEED`.
- Produces:
  - `OFFSETS_S: tuple[float, ...]` = −5.0 to +4.0 in steps of 0.5 (19 values).
  - `REFERENCES: tuple[str, ...] = ("binance_last_trade", "binance_trade_side_mid", "binance_ethusdt_1s_close")`
    (first is the primary).
  - `REFERENCE_LABELS: dict[str, str]` = `{"binance_last_trade": "Binance last trade",
    "binance_trade_side_mid": "Binance trade-side mid", "binance_ethusdt_1s_close": "Binance ETHUSDT 1 s"}`.
  - `daily_shifts(swaps: pl.DataFrame, refs: dict[str, pl.DataFrame], end_us: int,
    offsets: tuple[float, ...] = OFFSETS_S) -> pl.DataFrame` — long frame
    `reference, offset_s, day, d_fees_minus_lvr_usd, d_lp_fees_usd, n_unpriced`.
  - `robustness_table(daily: pl.DataFrame, shifts: pl.DataFrame, n_boot: int = N_BOOT, seed: int = SEED) -> pl.DataFrame`
    — one row per (reference, offset_s), in `REFERENCES` × `OFFSETS_S` order, columns
    `reference, offset_s, lp_fees_usd, lvr_usd, fees_minus_lvr_usd, ci_lo_usd, ci_hi_usd,
    shift_usd, shift_ci_lo_usd, shift_ci_hi_usd, n_unpriced`.
  - `crossing_offset(offsets: list[float], values: list[float]) -> float | None` — the offset
    where the curve last goes from ≥ 0 to < 0 (linear interpolation between grid points), None
    when it never does.

`swaps` is `aligned` (Swap rows) joined 1:1 with `swap_fees` on `(block_number, log_index)`, with
`day = block_timestamp.dt.date()`. Per swap and cell, with `P` the cell's price at `t0_us + d`:

```
X(P)      = amount_usdc + amount_eth * P - protocol_fee_usd(P)
shift     = X(P_cell) - X(p_cex_0)             # 0 when P_cell or p_cex_0 is null (counted)
d_lp_fees = lp_fee_weth(raw / 1e18) * (P_cell - p_cex_0)   # USDC fees do not move
```

where `protocol_fee_usd(P)` prices `protocol_fee_raw` at `P` when `fee_token == "WETH"` and at
1/1e6 when USDC. `daily` is `results/lvr_daily`'s frame (`day, fees_usd, lvr_0, ...`); a cell's
daily fees − LVR is `fees_usd − lvr_0 + d_fees_minus_lvr` (missing days in either frame → 0).
The bootstrap draws one index matrix exactly as `theory.day_bootstrap_sum` does
(`default_rng(seed).integers(0, n_days, size=(n_boot, n_days))`) and uses it for every cell, so
the primary 0 s interval equals `daily_summary`'s `fees_minus_lvr_ci_*`.

- [ ] **Step 1: Write the failing tests**

```python
def test_primary_zero_offset_cell_is_the_headline_and_its_interval() -> None:
    table = robustness.robustness_table(DAILY, robustness.daily_shifts(SWAPS, REFS, END))
    row = table.filter((pl.col("reference") == "binance_last_trade") & (pl.col("offset_s") == 0))
    assert row["fees_minus_lvr_usd"][0] == pytest.approx((DAILY["fees_usd"] - DAILY["lvr_0"]).sum())
    assert (row["ci_lo_usd"][0], row["ci_hi_usd"][0]) == pytest.approx(
        theory.day_bootstrap_sum((DAILY["fees_usd"] - DAILY["lvr_0"]).to_list()))
    assert row["shift_usd"][0] == 0 and row["shift_ci_lo_usd"][0] == row["shift_ci_hi_usd"][0] == 0

def test_shift_is_hand_computed_for_one_swap() -> None:
    # one swap: amount_usdc=-3000, amount_eth=1.0, WETH fee, protocol_fee_raw=1e15 wei,
    # p_cex_0=3000, price at t0+1 s = 3010 -> shift = (1.0 - 0.001) * 10 = 9.99
    ...

def test_missing_prices_give_zero_shift_and_are_counted() -> None:
    # a swap whose t0 + 4 s is past END -> n_unpriced == 1 in that cell, totals finite
    ...

def test_days_line_up_when_one_frame_lacks_a_day() -> None:
    # DAILY has a day with no swaps; shifts have zero for it; no NaN, same length draws
    ...

def test_crossing_offset() -> None:
    assert robustness.crossing_offset([-4, -3, -2], [0.2, -0.2, -0.5]) == pytest.approx(-3.5)
    assert robustness.crossing_offset([-1, 0], [-0.1, -0.2]) is None
```

Build `SWAPS`, `REFS`, `DAILY`, `END` as small module-level fixtures in the test file (two or
three days, a handful of swaps, hand-made reference tables).

- [ ] **Step 2: Run** `uv run pytest tests/test_robustness.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `lp/robustness.py` with the interfaces above.
- [ ] **Step 4: Run** — Expected: pass.
- [ ] **Step 5: Commit** — `git commit -m "LP: reference x t0-offset robustness table with a paired day bootstrap"`

### Task 5: Winning-bid timing fetch

**Files:**
- Create: `src/uniswap_lp_economics/data/block_timing.py`
- Modify: `src/uniswap_lp_economics/config.py` (add `TIMING_RELAYS`), `src/uniswap_lp_economics/cli.py`
  (step `fetch-timing`, in `ALL_STEPS` right after `fetch-relays`, with its subcommand)
- Test: `tests/test_block_timing.py`, `tests/test_cli_all.py` (expected step order)

**Interfaces:**
- Consumes: `relays._get`, `relays.RelayBreaker`, `relays.sample_blocks`, `relays.PATH`.
- Produces:
  - `config.TIMING_RELAYS = ("https://titanrelay.xyz", "https://boost-relay.flashbots.net", "https://aestus.live")`.
  - `TIMING_FILE = "block_timing.parquet"`; `GENESIS_TIME_S = 1_606_824_023`; `BIDS_PATH =
    "/relay/v1/data/bidtraces/builder_blocks_received"`.
  - `TIMING_SCHEMA`: `block_number Int64, relay String, found Boolean, slot Int64, block_hash String,
    bid_ms Int64, offset_ms Int64, relays_unchecked String`.
  - `time_block(client, block: int, relays: tuple[str, ...] = TIMING_RELAYS, backoff_s: float = 1.0,
    breaker: RelayBreaker | None = None) -> dict[str, Any]` — first relay that delivered the block;
    `offset_ms = min(timestamp_ms of bids with the delivered block_hash) − (GENESIS_TIME_S + 12 × slot) × 1000`;
    not-found when no relay delivered it or the hash is absent from the bids.
  - `fetch_block_timing(raw_dir: Path, first: int, last: int, client: httpx.Client | None = None) -> pl.DataFrame`
    — resumable like `fetch_relay_sample` (blocks already in the file are skipped), batches per
    Ruling 4, writes `raw_dir / TIMING_FILE`.
  - `timing_summary(timing: pl.DataFrame) -> dict[str, Any]` — `{"n_timed", "n_queried",
    "p10_ms", "p50_ms", "p90_ms", "by_relay": [{"relay", "n", "p50_ms"}]}`; quantiles None when
    nothing is timed.

- [ ] **Step 1: Write the failing tests** (httpx `MockTransport`, as in `tests/test_relays.py`)

```python
def test_winning_bid_offset_from_slot_start() -> None:
    # delivered: [{"block_hash": "0xaa", "slot": "100"}]; bids: same hash at "1606825223944"
    # and "1606825224100", another hash earlier -> slot start (1606824023 + 1200) s -> 944 ms
    row = block_timing.time_block(client, 7, (R1,), backoff_s=0)
    assert row["found"] and row["offset_ms"] == 944 and row["slot"] == 100

def test_hash_missing_from_bids_is_not_found() -> None: ...
def test_tries_relays_in_order_and_skips_ones_without_the_block() -> None: ...
def test_fetch_resumes_and_adds_a_second_batch_below_150(tmp_path) -> None: ...
def test_timing_summary_with_nothing_timed_has_null_quantiles() -> None: ...
```

- [ ] **Step 2: Run** `uv run pytest tests/test_block_timing.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the module, `config.TIMING_RELAYS` and the CLI step (blocks range from
  `blocks.parquet` as `fetch_relays` does).
- [ ] **Step 4: Run** `uv run pytest tests/test_block_timing.py tests/test_cli_all.py -q` — Expected: pass.
- [ ] **Step 5: Commit** — `git commit -m "Data: winning-bid times from relays that keep bid history (fetch-timing)"`

### Task 6: Wire the table and timing into `ulpe lp` (with R6)

**Files:**
- Modify: `src/uniswap_lp_economics/lp/analyze.py` (`LpInputs`, `load_lp_inputs`, `lp_analysis`)
- Modify: `src/uniswap_lp_economics/lp/checks.py` (add `check_r6_robustness`)
- Modify: `tests/lpworld.py` (write a small `block_timing.parquet`), `tests/test_lp_analyze.py`

**Interfaces:**
- Consumes: Task 3, 4, 5 functions.
- Produces:
  - `check_r6_robustness(identity_primary_usd: float, flash_lp_fees_usd: float, headline_usd: float) -> CheckResult`,
    name `"R6 robustness table reproduces the headline (reported)"`, `reported=True`.
  - `results/reference_robustness.csv` and `.md` (the table; the `.md` also lists
    `proxy_quality` at swap t0s and a note on the method).
  - `results/block_timing.csv` (the timed rows) and `results/block_timing.md` (`timing_summary`).
  - `summary.json["lp"]["robustness"]` =
    `{"crossing_offset_s": {reference: float | None}, "timing": timing_summary(...),
    "fees_minus_lvr_at_median_timing_usd": float | None, "largest_reference_shift_0s_usd": float,
    "protocol_fees_share_of_gap": float, "proxy_quality": {...}}`.
    `fees_minus_lvr_at_median_timing_usd` interpolates the primary line at `p50_ms / 1000` s;
    `protocol_fees_share_of_gap = protocol_fees_usd / -fees_minus_lvr_usd`.

Flash-loan LP fees for R6: accrued steps' `fee_usd` on rows whose `(block_number, log_index)` is
not a Swap row in `aligned`. Load timing with `_need(raw / block_timing.TIMING_FILE, "fetch-timing")`.

- [ ] **Step 1: Write the failing test** — extend `test_lp_analysis_end_to_end` to assert the two
  new results files exist, `summary["lp"]["robustness"]` has the keys above, the primary 0 s row of
  `reference_robustness.csv` equals `summary["lp"]["fees_minus_lvr_usd"]`, and `lp_checks.md` shows
  R6 as "reported".
- [ ] **Step 2: Run** `uv run pytest tests/test_lp_analyze.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** — compute everything before the write block (the existing "nothing is
  written until every number is computed" rule), then write.
- [ ] **Step 4: Run the whole suite** `uv run pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** — `git commit -m "LP: robustness table, block timing and R6 in ulpe lp"`

### Task 7: Figure 13

**Files:**
- Create: `src/uniswap_lp_economics/viz/robustness.py`
- Modify: `src/uniswap_lp_economics/viz/data.py` (`SOURCES`, `TYPES`, `Results.robustness`,
  `Results.timing`, `LP_KEYS` gains `"robustness"`), `src/uniswap_lp_economics/viz/render.py`
  (`("13_reference_and_timing", robustness.reference_and_timing)`), `tests/vizfix.py`
- Test: `tests/test_viz_robustness.py`, `tests/test_viz_claims.py`

**Interfaces:**
- Consumes: `Results`, `style.frame`, `style.usd`, `style.fade_band` or `fill_between`,
  `robustness.REFERENCE_LABELS` (Task 4).
- Produces: `reference_and_timing(r: Results) -> Figure`;
  `title(crossings: dict[str, float | None], p10_s: float | None, curve_after_zero_negative: bool) -> str`.

Drawing (spec section 6): x −5…+4 s, y fees − LVR in $M; three lines labelled at their right ends
(primary solid in `p.lvr`, the others thinner in `p.muted`), no legend; zero line; a dot on the
primary line at 0 s; the primary line's bootstrap band (`ci_lo_usd`…`ci_hi_usd`) only; a dashed
horizontal at `−protocol_fees_usd` labelled "protocol fee cut"; a shaded vertical band from p10 to
p90 of the timing (ms → s) labelled "winning bids". No band when nothing is timed.

Title rule:
- Every reference negative at every offset ≥ 0 s, and the latest crossing (closest to 0) is
  before the timing p10 (or no timing): `"LPs lose at every reference unless prices are read
  {abs(latest crossing):.1f} s before the slot"`.
- No reference crosses inside the range: `"LPs lose at every reference and every offset from −5 s to +4 s"`.
- Otherwise: `"Whether LPs lose depends on when the reference price is read"`.

Subtitle: `"Fees − LVR with the reference read at slot start + offset. At 0 s (the headline)
{usd(primary 0 s)}; at the median winning bid (+{p50:.1f} s) {usd(at median)}. Dashed: the
protocol's fee cut ({usd(protocol fees)})."` — drop the median clause when nothing is timed.
Source: `"Winning bids: 10th–90th percentile on {n_timed} blocks delivered through Titan,
Flashbots and Aestus; ultrasound, the largest relay, keeps no bid history for this window. Band on
the primary line: 95% day bootstrap."` — when nothing is timed: `"No winning-bid times were
available. Band: 95% day bootstrap."`

- [ ] **Step 1: Write the failing tests**

```python
def test_title_claims_the_crossing_only_when_the_data_supports_it() -> None:
    assert robustness.title({"a": -3.3, "b": -3.9}, 0.9, True).endswith("read 3.3 s before the slot")
    assert robustness.title({"a": None, "b": None}, 0.9, True).startswith("LPs lose at every reference and every offset")
    assert robustness.title({"a": 1.0}, 0.9, False).startswith("Whether LPs lose")
    assert robustness.title({"a": 1.2}, 0.9, True).startswith("Whether LPs lose")  # inside the band

def test_figure_renders_without_timing(tmp_path) -> None:
    # vizfix frames with summary lp.robustness.timing quantiles None -> renders, no "winning bids" text
```

Add `reference_robustness.csv` and `summary["lp"]["robustness"]` to `vizfix.fixture_frames` /
`write_results` so every parametrised render test in `test_viz_render.py` covers figure 13.

- [ ] **Step 2: Run** `uv run pytest tests/test_viz_robustness.py tests/test_viz_render.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite** — Expected: all pass (the parametrised render, stranded-word,
  off-canvas and determinism tests now include figure 13).
- [ ] **Step 5: Commit** — `git commit -m "Figures: 13 reference and timing robustness"`

### Task 8: Run on real data and check by eye

No new code; fixes found here go back through TDD in the task that owns the code.

- [ ] **Step 1:** `uv run ulpe fetch-timing` (free relay calls, several minutes; run in the
  background). Expected: `data/raw/block_timing.parquet`, at least 150 timed blocks, offsets
  mostly between 0 and 2,000 ms.
- [ ] **Step 2:** `uv run ulpe analyze` then `uv run ulpe lp`. Expected: both PASS; A5/A6 and
  R1–R6 "reported"; the primary 0 s row equals the summary's −$1,059,610; the 0 s and ±1…4 s
  values agree with the spec's exploration table within about $5k (the flash-loan constant and
  rounding); every other existing result unchanged (`git diff --stat results/` shows only the new
  files, `summary.json`, `lp_checks.*` and `analysis_checks.*`).
- [ ] **Step 3:** `uv run ulpe figures`, then render PNG previews to the scratchpad and look at
  every figure. Check figure 13: title true, band where the data puts it, labels clear, nothing
  clipped. Show the user figure 13 before committing.
- [ ] **Step 4: Commit** results and figures —
  `git commit -m "Results: robustness table, block timing and figure 13 on real data"`

### Task 9: README, methodology, roadmap

**Files:** `README.md`, `docs/methodology.md`, `docs/roadmap.md`,
`docs/superpowers/specs/2026-10-21-reference-robustness-design.md` (Rulings 1 and 2)

- [ ] **Step 1:** New README chapter "Is it the reference price?" after "Where LVR goes": figure
  13, then the spec's success paragraph with the computed numbers from `summary.json` and
  `results/reference_robustness.md`; the Contents line gains it.
- [ ] **Step 2:** TL;DR: the protocol-fee split ("before the protocol's cut, total fees nearly
  cover LVR ($X vs $Y); the $Z fee switch turns a borderline result into a clear loss"), numbers
  from `summary.json`.
- [ ] **Step 3:** Limitations: the reference-price and t0 bullets point to the new chapter; add
  the trade-side proxy's crossed share and the timing coverage caveat. Repo map: `lp/robustness.py`,
  `data/block_timing.py`; Reproduce: `ulpe fetch-timing`.
- [ ] **Step 4:** `docs/methodology.md`: the proxy, the offset grid, the shift method, the paired
  bootstrap, the timing method. Roadmap: sub-project 4 done, drop the figure-12 bullet. Spec: note
  Rulings 1 and 2.
- [ ] **Step 5:** Check every number in the new README text against `summary.json` (grep each
  one), run the full checks, commit — `git commit -m "Docs: reference and timing robustness chapter"`
