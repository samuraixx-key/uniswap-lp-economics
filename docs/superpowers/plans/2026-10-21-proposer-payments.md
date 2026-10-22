# Proposer-Payment Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the self-built fallback with five chain-only block classes, test the payout
rule on a blind stratified relay holdout, and let a pre-registered bar decide whether the README
states one proposer/builder split or keeps the two-split hedge.

**Architecture:** A fourth builder table (`last_tx.parquet`, 15.2 GB) gives each block's last
`to_address` and gas. A new module `lp/payouts.py` turns `block_revenue` + `last_tx` into the five
classes, types payout recipients from RPC code reads, and draws the holdout. `fetch-relays` gains
a `round` column, retries unchecked rows and fetches the holdout. `ulpe lp` computes the R1 parts
and the decision, then picks the split mechanically: the code, not a person, applies the bar.

**Tech Stack:** Python 3.13, polars, httpx (MockTransport in tests), google-cloud-bigquery,
matplotlib, pytest, ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-10-21-proposer-payments-design.md` (committed b8b89ac,
before any holdout relay call).

## Global Constraints

- Payout address: sender S != F sent the last transaction in at least **50** of F's blocks, with
  value > 0 in at least **99%** of them. Never tuned after this point.
- Holdout: seed **44**, the existing 1,000 sample blocks excluded, **300** class-3 blocks and
  **300** from classes 2, 4 and 5 together; written to disk before its first relay call; never
  redrawn.
- Decision: one split only if, among found holdout blocks in class 3, at least **95%** match the
  relay within 1 wei **and** at least **95%** pay the relay's `proposer_fee_recipient`.
  Otherwise the rule stays, the holdout result is published, the two-split hedge stays.
- R1, R1b, R1c and the decision are reported; nothing here fails the pipeline.
- The `last_tx` query selects `to_address` and `receipt_gas_used`, never `input`. The paid run
  happens only after the user has seen the dry-run byte count.
- Relay calls and RPC reads are free; reuse `relays._get`, `RelayBreaker`, `RpcClient.get_code`
  and `chain_state.parse_code`. Never read `.env`; never print the RPC URL.
- Never use the word "toxicity". Renders stay byte-deterministic; `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy src` and `uv run pytest -q` stay clean.
- Work on branch `proposer-payments`; merge to `main` only after the final review and the
  user's OK. Commits carry no AI attribution lines.

## Rulings made while planning

1. **The decision is applied in code.** `ulpe lp` builds the split with the payout class
   (`payouts=True`), computes the holdout decision on it, and keeps that split only when the
   decision passes; otherwise it rebuilds the old split (`payouts=False`) and keeps
   `sensitivity_self_built`. `summary.json` records `proposer_split: "one" | "hedge"`. This
   implements both outcomes of spec section 7 with one switch, and the hero reads the switch.
2. **The hero keeps its hatched-slice code.** It already draws nothing hatched when the moved
   amount is 0; it now treats a missing `sensitivity_self_built` as 0. No deletion is needed for
   the one-split outcome, and the hedge outcome still works.
3. **Recipient code is read in a new free step, `ulpe fetch-payout-code`**, run after
   `fetch-builders` in `ulpe all`, cached in `data/raw/builders/payout_recipient_code.parquet`.
4. **Empty blocks are their own class in both outcomes**, so the self-built count drops from
   105,536 to 105,361 even under the hedge.
5. **Builder dollars per class** are single-pool `builder_paid_usd` summed by block (the
   denominator of the exploration's $1,443,431).

## Review Focus

1. A non-empty block with no `last_tx` row (a gap in the BigQuery table) must raise with the
   block number, not silently fall into class 4 or 5 (Task 2 test).
2. A last transaction with a null `to_address` (a contract creation) is not a payment: not
   class 3, no crash (Task 2 test).
3. Relay recipients may come checksum-cased; BigQuery addresses are lowercase. Compare
   lowercased, or R1b fails every block (Task 6 test).
4. A holdout with zero found class-3 blocks must decide "hedge", never pass on an empty set or
   divide by zero (Task 6 test).
5. Re-running `fetch-relays` after the holdout is drawn must reuse the file and never redraw; a
   stratum with fewer than 300 candidates must raise before anything is written (Task 5 test).

---

### Task 1: The last-transaction table

**Files:**
- Modify: `src/uniswap_lp_economics/data/builders.py`
- Test: `tests/test_builders.py`

**Interfaces:**
- Produces: `LAST_TX = "last_tx.parquet"`; `build_last_tx_query(start: date, end: date) -> str`;
  `load_last_tx(raw_dir: Path) -> pl.DataFrame` with `block_number: Int64`,
  `to_address: String` (nullable), `receipt_gas_used: Int64`.

- [ ] **Step 1: Write the failing tests**

```python
def test_last_tx_query_reads_no_calldata() -> None:
    q = builders.build_last_tx_query(date(2026, 7, 1), date(2026, 10, 1))
    assert "to_address" in q and "receipt_gas_used" in q and "input" not in q
    assert "MAX(transaction_index) OVER (PARTITION BY block_number)" in q

def test_load_last_tx_names_the_command_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="fetch-builders"):
        builders.load_last_tx(tmp_path)
```

Extend `test_fetch_builders_writes_three_typed_tables_then_skips` (rename to `..._four_...`) and
the dry-run test so the fake client sees four queries and `last_tx.parquet` is written with the
types above.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_builders.py -q`
Expected: FAIL (`build_last_tx_query` missing; three tables written).

- [ ] **Step 3: Implement**

The query is the one dry-run at 15.2 GB: `SELECT block_number, to_address, receipt_gas_used FROM
transactions WHERE <window> QUALIFY transaction_index = MAX(transaction_index) OVER (PARTITION BY
block_number)`. Add it as the fourth job of `fetch_builders` with casts
`{"block_number": pl.Int64, "receipt_gas_used": pl.Int64}`; update the docstring's cost to "about
676 GB together". `load_builders` keeps its three-table return; `load_last_tx` is separate.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "Builders: last-transaction table (to_address, gas), 15.2 GB, behind the cost gate"
```

### Task 2: The five block classes

**Files:**
- Create: `src/uniswap_lp_economics/lp/payouts.py`
- Test: `tests/test_payouts.py`

**Interfaces:**
- Consumes: `block_revenue` (columns of `builders.load_builders()[0]`), `load_last_tx` (Task 1).
- Produces: constants `EMPTY, PAID, PAYOUT, PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED` (strings
  `"empty", "paid", "payout", "proposer_is_fee_recipient", "unexplained"`),
  `PAYOUT_MIN_BLOCKS = 50`, `PAYOUT_MIN_POSITIVE_SHARE = 0.99`;
  `payout_pairs(block_revenue: pl.DataFrame) -> pl.DataFrame` (`miner`, `last_from`);
  `block_classes(block_revenue: pl.DataFrame, last_tx: pl.DataFrame) -> pl.DataFrame` with
  `block_number, miner, last_from, last_value_wei, to_address, receipt_gas_used, cls`;
  `class_counts(classes) -> dict[str, int]` including `n_top_up`.

- [ ] **Step 1: Write the failing tests**

Build one synthetic `block_revenue` + `last_tx` with fee recipients A (builder), B (never pays),
C (builder whose payout pair has 49 blocks):

```python
def test_each_block_gets_one_class() -> None:
    c = block_classes(rev, last).to_dicts()
    cls = {r["block_number"]: r["cls"] for r in c}
    assert cls[1] == EMPTY                      # no transactions
    assert cls[2] == PAID                       # last_from == miner
    assert cls[3] == PAYOUT                     # A's payout sender, value > 0, to proposer
    assert cls[4] == UNEXPLAINED                # A's payout sender, value 0
    assert cls[5] == UNEXPLAINED                # top-up: payout sender pays A itself
    assert cls[6] == UNEXPLAINED                # to_address null (contract creation)
    assert cls[7] == PROPOSER_IS_FEE_RECIPIENT  # B: no paid or payout block anywhere

def test_payout_threshold_is_50_blocks_and_99_percent() -> None:
    # 49 blocks -> no pair; 50 -> pair; 50 blocks with one value-0 block (98%) -> no pair
    ...

def test_a_non_empty_block_without_a_last_tx_row_raises() -> None:
    with pytest.raises(ValueError, match="block 2"):
        block_classes(rev, last.filter(pl.col("block_number") != 2))

def test_class_counts_report_top_ups() -> None:
    assert class_counts(block_classes(rev, last))["n_top_up"] == 1
```

The payout pair needs ≥ 50 blocks, so generate A's payout blocks in a loop (block numbers
100–149); keep the named blocks 1–7 for the assertions.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_payouts.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Order exactly as spec section 4: empty (`last_from` null) → paid → payout (pair member, this
block's value > 0, `to_address` not null and != miner) → proposer-is-fee-recipient (miner has no
block in paid or payout) → unexplained. `n_top_up` counts blocks of a payout pair whose
`to_address == miner`. Join `last_tx` left on `block_number`; raise `ValueError` naming the first
non-empty block with no row.

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest tests/test_payouts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uniswap_lp_economics/lp/payouts.py tests/test_payouts.py
git commit -m "Payouts: five chain-only block classes (N = 50, 99%), top-ups and gaps caught"
```

### Task 3: Split from the classes, and the per-class dollars

**Files:**
- Modify: `src/uniswap_lp_economics/lp/destination.py` (`block_split`, new `class_table`)
- Test: `tests/test_destination.py`

**Interfaces:**
- Consumes: `block_classes` (Task 2).
- Produces: `block_split(block_revenue: pl.DataFrame, classes: pl.DataFrame, payouts: bool) ->
  pl.DataFrame` (same columns as now plus `cls`, `to_address`, `last_value_wei`); `class_table(classes:
  pl.DataFrame, single: pl.DataFrame) -> pl.DataFrame` with `cls, blocks, share_blocks,
  builder_paid_usd, share_builder_paid_usd`, rows in the order of the five constants.

- [ ] **Step 1: Write the failing tests**

```python
def test_split_pays_from_the_payout_address_only_when_asked() -> None:
    on = block_split(rev, classes, payouts=True).row(by_predicate=pl.col("block_number") == 3, named=True)
    off = block_split(rev, classes, payouts=False).row(by_predicate=pl.col("block_number") == 3, named=True)
    assert on["payment_wei"] == on["last_value_wei"] and not on["self_built"]  # block 3: class payout
    assert off["payment_wei"] == off["revenue_wei"] and off["self_built"]

def test_empty_blocks_are_not_self_built() -> None:
    assert not block_split(rev, classes, payouts=False).filter(pl.col("cls") == EMPTY)["self_built"].any()

def test_class_table_shares_sum_to_one() -> None:
    t = class_table(classes, single)
    assert t["cls"].to_list() == [EMPTY, PAID, PAYOUT, PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED]
    assert t["share_blocks"].sum() == pytest.approx(1) and t["share_builder_paid_usd"].sum() == pytest.approx(1)
```

Update every existing `block_split(...)` call in `tests/test_destination.py` to pass classes built
from its revenue frame with `payouts=False`; their expected numbers must not change.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_destination.py -q`
Expected: FAIL (signature).

- [ ] **Step 3: Implement**

`payment_wei` = `last_value_wei` for `paid`, and for `payout` when `payouts`; `revenue_wei`
otherwise (0 for empty). `self_built` = not empty and payment came from the fallback.
`sensitivity_self_built` and `paid_block_ratio` are unchanged. Grep `block_split(` and fix every
caller (`lp/analyze.py`, `lp/checks.py` tests).

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "Destination: split from the block classes; empty blocks no longer self-built; class table"
```

### Task 4: Relay rounds and retries

**Files:**
- Modify: `src/uniswap_lp_economics/data/relays.py`
- Test: `tests/test_relays.py`

**Interfaces:**
- Produces: `RELAY_SCHEMA["round"] = pl.String` with values `"seen" | "retry" | "holdout"`;
  `query_block(..., timeout_s: float = 30)` (passed down to `_get`);
  `retry_unchecked(raw_dir: Path, client: httpx.Client | None = None, relay_urls: tuple[str, ...]
  = RELAYS, pace_s: float = 0.5, timeout_s: float = 60) -> int` (rows retried).

- [ ] **Step 1: Write the failing tests**

```python
def test_an_old_file_without_round_reads_as_seen(tmp_path: Path) -> None: ...
def test_retry_requeries_only_unchecked_not_found_rows(tmp_path: Path) -> None:
    # rows: found (round seen), not-found all-answered, not-found with relays_unchecked
    # MockTransport counts calls: only the third block is queried; it is replaced, round "retry"
def test_a_retried_block_still_unfound_keeps_its_unchecked_relays(tmp_path: Path) -> None: ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_relays.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

The base sample keeps its behaviour and writes `round = "seen"`. `retry_unchecked` re-queries
not-found rows whose `relays_unchecked` is set, with a fresh `RelayBreaker`, `time.sleep(pace_s)`
between blocks and `timeout_s` per call, replaces those rows in place (exact wei kept, written
every 100 blocks and in `finally`, as `fetch_relay_sample` does). Print how many stay unchecked
and on which relays.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "Relays: round column, paced retries of blocks a relay never answered"
```

### Task 5: The holdout draw and fetch, and the two new CLI steps

**Files:**
- Modify: `src/uniswap_lp_economics/lp/payouts.py` (`draw_holdout`, `recipient_reads`,
  `recipient_types`), `src/uniswap_lp_economics/data/relays.py` (`fetch_holdout`),
  `src/uniswap_lp_economics/data/builders.py` (`fetch_payout_code`),
  `src/uniswap_lp_economics/cli.py` (`fetch-relays`, new `fetch-payout-code`, `ulpe all` order)
- Test: `tests/test_payouts.py`, `tests/test_relays.py`, `tests/test_cli_all.py`

**Interfaces:**
- Consumes: `block_classes` (Task 2), `retry_unchecked` (Task 4), `chain_state.parse_code`.
- Produces:
  - `HOLDOUT_SEED = 44`, `HOLDOUT_PER_STRATUM = 300`;
    `draw_holdout(classes: pl.DataFrame, exclude: set[int], seed: int = HOLDOUT_SEED, n: int =
    HOLDOUT_PER_STRATUM) -> pl.DataFrame` (`block_number`, `stratum` in `"payout" | "rest"`, `seed`).
  - `relays.HOLDOUT_FILE = "relay_holdout.parquet"`; `fetch_holdout(raw_dir: Path, classes:
    pl.DataFrame, client=None, relay_urls=RELAYS, pace_s=0.5, timeout_s=60) -> Path`.
  - `recipient_reads(classes) -> list[tuple[str, int]]`: for class-3 payments with gas > 21,000,
    each distinct `to_address` at its first and last payment block.
  - `builders.PAYOUT_CODE = "payout_recipient_code.parquet"`; `fetch_payout_code(client:
    RpcClient, raw_dir: Path, reads: list[tuple[str, int]]) -> Path` (cached, `address, block,
    code`).
  - `recipient_types(classes, code: pl.DataFrame, block_usd: pl.DataFrame) -> tuple[pl.DataFrame,
    int]`: per type `wallet | 7702_wallet | contract`: `payments, blocks, paid_eth,
    builder_paid_usd`; and the number of recipients whose two reads differ.

- [ ] **Step 1: Write the failing tests**

```python
def test_holdout_is_stratified_seeded_and_excludes_the_old_sample() -> None:
    h = draw_holdout(classes_with_many_blocks, exclude={...}, n=3)
    assert h.group_by("stratum").len().sort("stratum").to_dicts() == [{"stratum": "payout", "len": 3}, {"stratum": "rest", "len": 3}]
    assert h.equals(draw_holdout(classes_with_many_blocks, exclude={...}, n=3))  # deterministic
    assert not set(h["block_number"]) & {...}
    assert set(h.filter(pl.col("stratum") == "rest")["block_number"]) <= blocks_of(PAID, PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED)

def test_a_small_stratum_raises_before_writing(tmp_path: Path) -> None: ...

def test_holdout_file_exists_before_the_first_relay_call(tmp_path: Path) -> None:
    # the MockTransport handler asserts (tmp_path / relays.HOLDOUT_FILE).exists() on every call
def test_rerun_reuses_the_holdout_and_never_redraws(tmp_path: Path) -> None: ...

def test_recipient_types_prefer_7702_then_contract() -> None:
    # reads: X empty/empty -> wallet; Y empty/0xef0100+addr -> 7702_wallet (differs: 1);
    # Z 0x6080.../0x6080... -> contract; gas == 21000 payments are wallets without a read
```

In `tests/test_cli_all.py`, assert `fetch-payout-code` follows `fetch-builders` and precedes
`fetch-relays` in the step list.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_payouts.py tests/test_relays.py tests/test_cli_all.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`draw_holdout`: candidates sorted by block number, `random.Random(seed).sample` per stratum
(payout first, then rest), raise `ValueError` if a stratum has fewer than `n`. `fetch_holdout`:
if the file exists, read it (raise if its seed is not 44); else draw and `write_exact` it, then
query each holdout block not yet in `relays.parquet` with `query_block` and append with
`round = "holdout"`. `cli.fetch_relays`: base sample → `retry_unchecked` → `fetch_holdout` when
`last_tx.parquet` exists (else print that the holdout waits for `fetch-builders`).
`cli.fetch_payout_code`: classes from the builder tables, `fetch_payout_code(rpc(), ...)`.
`recipient_types` uses `parse_code`: any delegate → `7702_wallet`; else any code → `contract`;
else `wallet`.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "Holdout: stratified seed-44 draw written before any relay call; payout recipient types"
```

### Task 6: R1 in three parts, R1b, R1c and the decision

**Files:**
- Modify: `src/uniswap_lp_economics/lp/checks.py` (`check_r1_relays`, new `holdout_decision`)
- Test: `tests/test_destination.py` (replace `test_reported_checks_r1_and_r2`'s R1 half and
  `test_r1_counts_not_found_blocks_by_relay_coverage`)

**Interfaces:**
- Consumes: `block_split(..., payouts=True)` (Task 3), the `round` column (Task 4).
- Produces: `HOLDOUT_BAR = 0.95`; `check_r1_relays(relays, split, block_usd: pl.DataFrame) ->
  CheckResult` (`block_usd`: `block_number, builder_paid_usd`, single-pool, summed per block)
  whose summary has `by_round: {seen|retry|holdout: {cls: {sampled, found, match_within_1_wei,
  match_within_1pct, recipient_match}}}`, `holdout_by_stratum`, `r1c_breaking_blocks:
  [{block_number, builder_paid_usd}]` (0 for a block with no single-pool swap), `unexplained_by_relay`
  (delivering relay of found unexplained blocks, `relays_unchecked` of unfound ones), and the old
  top-level counts; `holdout_decision(relays, split) -> dict` with `n_found_payout`,
  `share_within_1_wei`, `share_within_1pct`, `share_recipient_match`, `one_split: bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_decision_passes_at_95_percent_on_both() -> None:   # 20 found payout blocks, 19 exact, 19 recipient -> one_split
def test_decision_fails_below_the_bar_on_either() -> None:  # 18/20 exact -> hedge
def test_decision_with_no_found_payout_blocks_is_hedge() -> None:
    assert holdout_decision(relays_without_holdout, split)["one_split"] is False
def test_only_holdout_payout_rows_decide() -> None:          # bad seen/retry rows and bad paid rows do not move it
def test_recipient_match_ignores_address_case() -> None:     # relay "0xABc..." vs to_address "0xabc..."
def test_r1c_lists_fee_recipient_blocks_delivered_for_someone_else() -> None: ...
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_destination.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Rows with a null `round` count as `seen`. `recipient_match` is computed for `paid` and `payout`
rows that have a non-empty `proposer_fee_recipient`, comparing lowercased. `one_split` requires
`n_found_payout > 0` and both shares `>= HOLDOUT_BAR`. Both stay `reported=True`.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "R1 by round and class, recipient check, R1c listing, pre-registered holdout decision"
```

### Task 7: Wire `ulpe lp`, the results file and the hero

**Files:**
- Modify: `src/uniswap_lp_economics/lp/analyze.py` (inputs, split choice, summary, `lvr_destination.md`)
- Modify: `src/uniswap_lp_economics/lp/destination.py` (`LIMITATION_TEXT`, `LIMITATION_TEXT_HEDGE`)
- Modify: `src/uniswap_lp_economics/viz/hero.py:237-238`
- Test: `tests/test_lp_analyze.py`, `tests/test_viz_hero.py`, `tests/vizfix.py` if its summary needs the new keys

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: `summary["lp"]["destination"]` gains `proposer_split`, `holdout_decision`,
  `block_classes` (rows of `class_table`), `recipient_types`, `n_recipients_reads_differ`,
  `n_top_up`; `sensitivity_self_built` only when `proposer_split == "hedge"`. `LpInputs` gains
  `last_tx` and `payout_code` (via `_need(..., "fetch-builders")` / `"fetch-payout-code"`).

- [ ] **Step 1: Write the failing tests**

```python
def test_one_split_drops_the_sensitivity(...) -> None:      # decision passes -> no sensitivity key, proposer_split "one"
def test_hedge_keeps_the_sensitivity(...) -> None:           # decision fails -> key present, payouts=False split used
def test_hero_without_a_sensitivity_draws_nothing_hatched(tmp_path: Path) -> None:
    # summary fixture with the key removed: no hatched PathPatch, plain end labels, footnote lacks "Hatched"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_lp_analyze.py tests/test_viz_hero.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `lp_analysis`: classes → `split1 = block_split(..., payouts=True)` → decision → `split =
split1` if `one_split` else `block_split(..., payouts=False)`; R1 runs on `split1` with
`block_usd` summed from the single-pool rows of `searcher_costs`. `lvr_destination.md`: "Totals", then
"Block classes" and "Payout recipients", then the sensitivity section only under the hedge; notes
are `DESTINATION_NOTE`, a new `CLASSES_NOTE` (the rule, its two thresholds, and the unexplained
share of blocks and dollars, read from the class table), `SENSITIVITY_NOTE` only under the hedge,
and the limitation text for the outcome. `LIMITATION_TEXT` (one split): proposer payments are the
block's last transaction from the fee recipient or from a payout address learned from chain data,
tested on a blind relay holdout; the unexplained remainder is given the whole builder revenue.
`LIMITATION_TEXT_HEDGE` is the current text. Hero: `sens = dest.get("sensitivity_self_built")`
and `moved = 0.0` when it is None.

- [ ] **Step 4: Run the suite and the checks**

Run: `uv run pytest -q; uv run ruff check .; uv run ruff format --check .; uv run mypy src`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "ulpe lp: block classes, R1 parts and the decision pick the split; hero reads it"
```

### Task 8: Real data (user gates on the paid query)

No code. Each command's output goes into the task report.

- [ ] **Step 1:** `uv run ulpe fetch-builders --dry-run`. **Stop and show the user the
  `last_tx.parquet` byte count** (about 15.2 GB expected). Continue only on their OK.
- [ ] **Step 2:** `uv run ulpe fetch-builders --confirm-cost` (the three existing tables are
  skipped). Expected: `last_tx.parquet` with one row per non-empty window block (659,624).
- [ ] **Step 3:** `uv run ulpe fetch-payout-code`. Report the number of reads and recipients.
- [ ] **Step 4:** `uv run ulpe fetch-relays` (run in the background; it is slow by design).
  Expected: `relay_holdout.parquet` written first (600 blocks, seed 44); retries and holdout rows
  appended with their rounds. Report how many stay unchecked, and on which relay.
- [ ] **Step 5:** `uv run ulpe lp`. Report the class table, R1 by round, R1c, the unexplained
  blocks' relays, the recipient types and `holdout_decision` verbatim.
- [ ] **Step 6: Commit** the results files (`git add results; git commit -m "Results: block classes, relay holdout and the proposer-split decision"`).

### Task 9: Figures and docs for the outcome

**Files:**
- Modify: `README.md`, `docs/methodology.md` (sections 15, 16 R1 row, limitation text, section
  with the R1 notes), `docs/roadmap.md`, `results/figures/*` (regenerated)

- [ ] **Step 1:** `uv run ulpe figures`. Check by eye the hero, figure 08 and every data-checked
  title or subtitle that quotes the builders' or proposers' share (`grep -rn "proposer\|builder"
  src/uniswap_lp_economics/viz`).
- [ ] **Step 2: If `proposer_split == "one"`:** the README's "Where LVR goes" finding and the
  "Proposer versus builder" limitation state the one split with the numbers from `summary.json`,
  the unexplained share of blocks and of builder dollars, and the holdout result in one sentence;
  the sensitivity table and its paragraph go. Methodology 15 replaces "The self-built fallback,
  and a sensitivity" with the five classes, the rule and its thresholds, the class table, the
  recipient types; 16 gives R1 in three parts plus R1b, R1c and the decision.
  **If `"hedge"`:** README and methodology keep the two splits, add the class table, the holdout
  result as it stands and a sentence that the rule was not changed after it.
- [ ] **Step 3:** `docs/roadmap.md`: proposer-payment detection and relay retries move to Done
  with this spec and plan; the 261 GB query is recorded as dropped ($630 left, 0.04% of builder
  dollars, or the computed figure if it differs); the 7702 item notes that payout recipients are
  typed with 7702 wallets named as wallets; the BigQuery spend gains the 15.2 GB.
- [ ] **Step 4:** `uv run pytest -q` (the viz claim tests check titles against the data).
  Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add README.md docs results
git commit -m "Docs: proposer/builder split after the payout rule and the relay holdout"
```
