# Recipient check through forwarders: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the class fix, the seed-45 holdout (draw, relay fetch, payment paths), check R1d and the
second frozen decision, without touching the published seed-42/44 data.

**Architecture:** extend the existing modules in place: `lp/payouts.py` (classes, seeds),
`data/relays.py` (draw/fetch/retry, now parameterised by file, seed and round, with a guard on
the published rows), `data/transfers.py` (payment paths over `alchemy_getAssetTransfers`),
`lp/checks.py` (R1d, decision and freeze for a second round), `lp/analyze.py` (publish the second
decision once frozen), `cli.py` (`fetch-relays`, new `fetch-paths`).

**Tech Stack:** Python 3.13, polars 2.0, httpx, pytest (`uv run pytest`), ruff, mypy.

**Spec:** [`docs/superpowers/specs/2026-10-21-forwarder-recipient-check-design.md`](../specs/2026-10-21-forwarder-recipient-check-design.md) (tag `forwarder-preregistered`).

## Global Constraints

- Seed **45**; strata **300** class 3 and **300** classes 2/4/5; exclude every block in `relays.parquet`.
- Files: `data/raw/relay_holdout_2.parquet`, round label `holdout2`, `data/raw/holdout2_paths.parquet`, `data/raw/holdout_decision_2.json`.
- `relay_holdout.parquet` and `holdout_decision.json` are only read; rows of rounds `seen`, `retry`, `holdout` in `relays.parquet` never change.
- Bar **0.95** within 1 wei and **0.95** R1d, on found holdout-2 blocks in class 3; no minimum count.
- R1d hop: exactly one internal transfer from the current address, in the last transaction, value **≥** the payment; at most **3** hops; stop on a repeat.
- Payout pair needs the fee recipient to have at least one class-2 block.
- No BigQuery. No R1d on any block outside the seed-45 holdout.
- Commit messages carry no AI attribution lines.

## Review Focus

- A relay retry or holdout run that would rewrite a `seen`/`retry`/`holdout` row must refuse to write (Task 2 test `test_a_write_that_changes_a_published_row_refuses`).
- `ulpe fetch-relays` run twice must not re-query seed-44 not-found rows (Task 4 test `test_fetch_relays_retries_only_holdout2`).
- The last transaction from RPC disagreeing with the chain tables must stop the path fetch, not write a guessed path (Task 3 test `test_a_last_tx_mismatch_raises_and_writes_nothing`).
- The second decision must not freeze while a class-2/3 holdout-2 block lacks a path row (Task 5 test `test_holdout2_does_not_freeze_without_every_path`).
- An address in mixed case from the relay or the RPC must still match (Task 5 test `test_r1d_compares_lowercased`).

---

### Task 1: Class fix

**Files:** Modify `src/uniswap_lp_economics/lp/payouts.py` (`payout_pairs`, constants); Test `tests/test_payouts.py`.

**Interfaces:** Produces `HOLDOUT2_SEED = 45` in `lp/payouts.py`; `payout_pairs` and `block_classes` keep their signatures.

- [ ] **Step 1:** Write `test_a_fee_recipient_that_never_pays_has_no_payout_pair`: miner L with 60 blocks whose last transaction is from S with value > 0 to varying recipients and no block with `last_from == L` → `payout_pairs` has no row for L, and `block_classes` gives all 60 blocks `proposer_is_fee_recipient`. Existing tests must stay green (miner A pays itself in block 2).
- [ ] **Step 2:** Run `uv run pytest tests/test_payouts.py -q`; the new test fails.
- [ ] **Step 3:** In `payout_pairs`, keep only miners with at least one block where `last_from == miner` (semi-join). Docstrings of `payout_pairs`/`block_classes` say so in one line. Add `HOLDOUT2_SEED = 45`.
- [ ] **Step 4:** Run `uv run pytest tests/test_payouts.py -q`; all pass.
- [ ] **Step 5:** Commit `payouts: a payout pair needs a fee recipient that pays from itself (class fix)`.

### Task 2: Relay file guard, second draw and round-limited retry

**Files:** Modify `src/uniswap_lp_economics/data/relays.py`; Test `tests/test_relays.py`.

**Interfaces:**
- Produces `PUBLISHED_ROUNDS = ("seen", "retry", "holdout")`, `HOLDOUT2_FILE = "relay_holdout_2.parquet"`, `HOLDOUT2_ROUND = "holdout2"`, `HOLDOUT_ROUNDS = ("holdout", "holdout2")`.
- `fetch_holdout(raw_dir, classes, client=None, relay_urls=RELAYS, pace_s=0.5, timeout_s=60, n=HOLDOUT_PER_STRATUM, seed=HOLDOUT_SEED, holdout_file=HOLDOUT_FILE, round_label="holdout") -> Path` (defaults keep today's call working).
- `retry_unchecked(raw_dir, client=None, relay_urls=RELAYS, pace_s=0.5, timeout_s=60, rounds: tuple[str, ...] | None = None) -> int`: only rows whose `round` is in `rounds` (None = every round, today's behaviour). A retried row whose round is in `HOLDOUT_ROUNDS` keeps it.
- `_write(df: pl.DataFrame, out: Path) -> None`: every writer of `relays.parquet` goes through it.

- [ ] **Step 1:** Write the tests:
  - `test_a_write_that_changes_a_published_row_refuses`: file with a `holdout` not-found row; `retry_unchecked(..., rounds=None)` with a relay that now finds it → raises `ValueError` naming the published rows; file bytes unchanged.
  - `test_retry_limited_to_holdout2_leaves_other_rounds_alone`: unchecked rows in `holdout` and `holdout2`; `rounds=("holdout2",)` queries only the `holdout2` block, which keeps `round == "holdout2"`.
  - `test_second_holdout_has_its_own_file_seed_and_round`: `fetch_holdout(..., seed=45, holdout_file=HOLDOUT2_FILE, round_label="holdout2")` writes `relay_holdout_2.parquet` with seed 45 before the first relay call, excludes every block already in the relay file (including `holdout` rows), labels new rows `holdout2`, leaves `relay_holdout.parquet` bytes unchanged; a second file with another seed raises.
- [ ] **Step 2:** Run `uv run pytest tests/test_relays.py -q`; the new tests fail.
- [ ] **Step 3:** Implement. `_write` reads the file on disk (if any) and raises unless every on-disk row with `round` in `PUBLISHED_ROUNDS` appears identically in `df` (anti-join on all columns with `nulls_equal=True` is empty), then `write_exact`. Appending new published rows (a fresh sample) stays allowed.
- [ ] **Step 4:** Run `uv run pytest tests/test_relays.py -q`; all pass.
- [ ] **Step 5:** Commit `relays: guard published rounds, second holdout draw, round-limited retry`.

### Task 3: Payment paths

**Files:** Modify `src/uniswap_lp_economics/data/transfers.py`; Test `tests/test_transfers.py`.

**Interfaces:**
- `PATHS_FILE = "holdout2_paths.parquet"`; `PATH_SCHEMA = {"block_number": Int64, "tx_hash": String, "path": String}` (`path`: lowercase addresses joined by `,`, starting with `to_address`).
- `MAX_HOPS = 3`.
- `payment_path(client: RpcClient, block: int, to_address: str, value_wei: int) -> tuple[str, list[str]]`: one `eth_getBlockByNumber(block, true)`; its last transaction must have `to` == `to_address` and `value` == `value_wei` (lowercased), else `ValueError`; then hops via `fetch_internal_transfers(client, a, block, block)` filtered to that hash and `value_wei >= value_wei`.
- `fetch_payment_paths(client: RpcClient, raw_dir: Path, targets: pl.DataFrame) -> Path`: `targets` has `block_number`, `to_address`, `last_value_wei`; blocks already in the file are skipped; written every 50 blocks and on exit (`write_exact`); an exception propagates after the save.

- [ ] **Step 1:** Write tests with the existing `fake` client style (a handler keyed on method): one hop through a forwarder; two hops; two qualifying transfers → path stops at the splitter; a loop back to `to_address` stops; a transfer of value+dust is followed; a transfer in another transaction of the block is ignored; a fourth hop is not taken; `test_a_last_tx_mismatch_raises_and_writes_nothing`; a rerun skips blocks already in the file.
- [ ] **Step 2:** Run `uv run pytest tests/test_transfers.py -q`; the new tests fail.
- [ ] **Step 3:** Implement as specified.
- [ ] **Step 4:** Run `uv run pytest tests/test_transfers.py -q`; all pass.
- [ ] **Step 5:** Commit `transfers: payment paths through forwarders for the seed-45 holdout`.

### Task 4: CLI

**Files:** Modify `src/uniswap_lp_economics/cli.py`; Test `tests/test_cli_all.py`.

**Interfaces:** Consumes Task 2 and 3. `fetch_relays()` runs: `fetch_relay_sample`; if the last-tx table exists, `fetch_holdout` (seed 44, defaults) then `fetch_holdout(..., seed=HOLDOUT2_SEED, holdout_file=HOLDOUT2_FILE, round_label=HOLDOUT2_ROUND)`; then `retry_unchecked(config.RAW_DIR, rounds=(HOLDOUT2_ROUND,))`. New `fetch_paths()` and subcommand `fetch-paths` ("payment paths of the seed-45 holdout's paid/payout blocks (RPC)"), also in `ulpe all` after `fetch-relays`: targets = holdout-2 blocks whose class is `paid` or `payout`; message and no-op if `relay_holdout_2.parquet` is missing.

- [ ] **Step 1:** Write `test_fetch_relays_retries_only_holdout2` (records `retry_unchecked` kwargs, asserts `rounds == ("holdout2",)` and both holdout calls), update `test_the_holdout_waits_for_the_last_tx_table` for the new signature, and `test_fetch_paths_targets_paid_and_payout_holdout2_blocks`.
- [ ] **Step 2:** Run `uv run pytest tests/test_cli_all.py -q`; new tests fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest tests/test_cli_all.py -q`; all pass.
- [ ] **Step 5:** Commit `cli: seed-45 holdout in fetch-relays, fetch-paths`.

### Task 5: R1d and the second decision

**Files:** Modify `src/uniswap_lp_economics/lp/checks.py`; Test `tests/test_destination.py` (where the R1 tests live).

**Interfaces:**
- `ROUNDS = ("seen", "retry", "holdout", "holdout2")`; `HOLDOUT2_DECISION_FILE = "holdout_decision_2.json"`.
- `holdout_decision(relays, split, round_label="holdout", paths: pl.DataFrame | None = None) -> dict`: with `paths`, the recipient share is R1d; for `holdout2` the dict adds `"round": "holdout2", "recipient_check": "R1d"` (the round-1 dict is unchanged).
- `settle_decision(raw_dir, relays, fresh, decision_file=HOLDOUT_DECISION_FILE, holdout_file=HOLDOUT_FILE, round_label="holdout", ready: bool = True)`: freezes only when `ready` and every drawn block has a row of that round.
- `paths_complete(raw_dir: Path, split: pl.DataFrame, paths: pl.DataFrame) -> bool`: every holdout-2 block in class paid/payout has a path row.
- `check_r1_relays(relays, split, block_usd, paths: pl.DataFrame | None = None)`: the top-level base excludes both holdout rounds; `by_round["holdout2"]` parts gain `recipient_match_fwd` when `paths` is given; adds `holdout2_by_stratum` and `holdout2_recipient_failures` (found class-3 rows failing R1d).

- [ ] **Step 1:** Write the tests: R1d passes via a path, fails without the recipient on it, fails with no relay recipient; `test_r1d_compares_lowercased`; the round-1 decision dict is unchanged by passing `paths`; `test_holdout2_does_not_freeze_without_every_path`; a complete holdout-2 freezes into `holdout_decision_2.json` while `holdout_decision.json` keeps its bytes.
- [ ] **Step 2:** Run `uv run pytest tests/test_destination.py -q`; new tests fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest tests/test_destination.py -q`; all pass.
- [ ] **Step 5:** Commit `checks: R1d through forwarders and the frozen seed-45 decision`.

### Task 6: Publish the second decision

**Files:** Modify `src/uniswap_lp_economics/lp/analyze.py`; Test `tests/test_lp_analyze.py`.

**Interfaces:** `LpInputs.payment_paths` (empty frame with `PATH_SCHEMA` when the file is missing). In `lp_analysis`: decision 1 as today; decision 2 = `holdout_decision(relays, split_rule, "holdout2", paths)` settled with the holdout-2 files and `ready=paths_complete(...)`. Published decision = decision 2 if frozen, else decision 1. `dest` gains `holdout_decision_2`, `decision_2_frozen`, `holdout_decision_2_recomputed` (when any), `published_decision` (`"holdout"` or `"holdout2"`). Both decision lines are printed. `RULE_SPLIT_LABEL` names the check that failed (first holdout's R1b, or the second's R1d). `lvr_destination.md` gets a "Seed-45 holdout (R1d)" metrics table from `holdout_decision_2`.

- [ ] **Step 1:** Write the tests: without holdout-2 files the run publishes decision 1 and `published_decision == "holdout"`; a frozen passing decision 2 over a frozen failing decision 1 gives `proposer_split == "one"` and `published_decision == "holdout2"`; a frozen failing decision 2 keeps the hedge.
- [ ] **Step 2:** Run `uv run pytest tests/test_lp_analyze.py -q`; new tests fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src`; all clean.
- [ ] **Step 5:** Commit `ulpe lp: publish the seed-45 decision once frozen`.

### Task 7: Review before the draw

- [ ] Whole-branch review against the spec (superpowers:requesting-code-review); fix findings; suite green; push. **No draw before this is done.**

### Task 8: Draw, fetch, decide

- [ ] Record SHA-256 of `relay_holdout.parquet`, `holdout_decision.json`, `relays.parquet`; copy `relays.parquet` to `relays.before_seed45.parquet`.
- [ ] `uv run ulpe fetch-relays` (background), then again (the one retry).
- [ ] `uv run ulpe fetch-paths` until every target has a row.
- [ ] `uv run ulpe lp` (freezes `holdout_decision_2.json`), then `uv run ulpe figures`.
- [ ] Verify: the two seed-44 files' hashes unchanged; the published rows of `relays.parquet` equal the backup's.

### Task 9: Write up

- [ ] Methodology section 20 (the fix, R1d, the holdout, the frozen result) and a pointer from 19.2's "known flaw"; README (one split only if the bar passed); roadmap; spec status line; commit results; push; merge per superpowers:finishing-a-development-branch.
