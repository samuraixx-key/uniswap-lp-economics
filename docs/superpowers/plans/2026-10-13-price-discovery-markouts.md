# Price Discovery and Markouts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the validated swap, tick-book and Binance data into price-discovery and markout results
(`uv run ulpe analyze` → committed `results/`), including the chain available arbitrage → captured →
kept net of gas and builder payments.

**Architecture:**
- Pure modules hold the maths: `replay` (public event replay), `v3swap` (exact-integer V3 swap and
  arbitrage-to-price), `flows` (labels), `align` (as-of reference prices), `markouts`, `arbprofit`,
  `discovery`, `checks`.
- Thin I/O modules fetch the new raw data: `data/blocks` (BigQuery) and `data/transfers` (Alchemy).
- `report` and `figures` write tables and charts; `analyze` composes everything behind `ulpe analyze`.
- The central table is `aligned` (one row per swap). Price discovery uses a derived per-block series
  built by replaying the tick book block by block.

**Tech Stack:** Python 3.13, uv, polars, numpy, matplotlib (Agg), httpx, google-cloud-bigquery,
pytest, ruff, mypy --strict. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-13-price-discovery-markouts-design.md`. Read it before
starting. The spec was amended together with this plan (see "Rulings" below).

## Global Constraints

- Python 3.13 via uv. Run everything as `uv run <cmd>` from the repo root.
- **No new runtime or dev dependencies.** polars, numpy, matplotlib, httpx and google-cloud-bigquery
  are already in `pyproject.toml`.
- Pool `0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`: token0 USDC (6 decimals), token1 WETH
  (18 decimals), fee 500 pips, tick spacing 10. USDC `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48`,
  WETH `0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2`.
- Study window `[2026-07-01, 2026-10-01)` UTC. Snapshot block 25,433,938; the window's first block is
  25,433,939.
- **Pool state values are exact integers:** Python `int`, `pl.Int128` in memory, `Decimal(38, 0)` on
  disk via `io.write_exact` / `io.read_exact`. Floats only in USD, price and bp columns.
- Horizons `(0, 12, 60, 300, 3600)` seconds. Fee band 5 bp. Episode thresholds 5 and 10 bp.
  Bootstrap: 1,000 resamples over UTC days, seed 42. Size buckets `<1k`, `1k-10k`, `10k-100k`,
  `>=100k` (on `notional_usd`). Top bots: smallest prefix covering ≥ 90% of searcher notional, cap 25.
- **Never print, log or put `ETH_RPC_URL` into an exception message** (it holds the API key). Never
  read `.env`.
- Tests that touch the network are marked `@pytest.mark.live` and are skipped by default.
- Before every commit, run `uv run ruff format .`, then all four must pass: `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest -q`. Code blocks in this plan are
  the content to write; ruff may re-wrap them, which is fine.
- **Commit messages carry no `Co-Authored-By` or other attribution trailer** (user instruction).
  Push after every commit with `git push`; the user pre-approved pushes to this private repo.
- Matplotlib must use the Agg backend (CI has no display).
- **Real data:** the main checkout's `data/` holds the downloaded and built data. When working in a
  worktree, the controller sets `DATA_DIR` in the worktree's `.env` to that folder before Task 2.
  Steps that need real data say so.
- The builder-payment limitation text (spec section 9) is used verbatim; it lives in
  `report.LIMITATION_TEXT` (Task 14).

## Rulings (spec amendments made with this plan)

1. **Arbitrage target prices (spec 6.5).** The spec's defining sentence ("marginal price after the
   fee equals `P_cex`") is binding; its example formulas were inverted. With fee `f` and Binance fee
   `c`: a cheap pool is bought until `P_pool = P_cex·(1−f)·(1−c)`; an expensive pool is sold into until
   `P_pool = P_cex·(1+c)/(1−f)`. Task 4 tests that this amount maximises profit.
2. **`v3swap` is an exact-integer port of the V3 swap**, not float math. **A1's tolerance:** final
   `sqrtPriceX96` relative error < 1e-9, and output amount within `max(2 raw units, 1e-9 × |out|,
   2 raw input units valued at the pre-swap pool price)`. The event does not record whether the
   original call was exact-input or exact-output, or its price limit, so an exact-input
   re-simulation can differ by rounding on the last step. Exact-output swaps round their input up by
   about one raw input unit; valuing that unit at the pre-swap pool price covers dust exact-output
   swaps whose whole input is rounding. A1 also reports the bit-exact match count.
3. **A2.** In a single-pass replay, "start state equals the previous block's end state" holds by
   construction. A2 still checks it, and adds two independent checks: every block's end price equals
   the last swap's `sqrtPriceX96` in that block, and blocks without pool events end in the state they
   started in.
4. **Bot transfers are cached per contract** in `data/raw/bot_transfers/<address>.parquet` (the spec's
   single `bot_transfers.parquet` becomes a folder), so reruns fetch only new contracts.
5. **`align.py` holds the as-of reference logic only.** `analyze.build_aligned` composes labels,
   reference prices, markouts and costs into `aligned.parquet`.
6. **Reference coverage (A4) uses the data end, not the last trade:** a reference at time `t` is null
   when `t` is at or after the window end (2026-10-01 00:00 UTC) or before the first reference point.

## Review Focus

1. **Empty groups.** No gap episodes at 10 bp, no top bots, or a label with no swaps must still give
   tables (header only) and charts (marked "no data"), not a crash. Tests: Task 12
   `test_find_episodes_none`, Task 14 `test_figures_handle_empty_inputs`.
2. **Horizons past the data end.** A swap in the last hour must get a null 1h reference, not the
   stale last Binance trade. Test: Task 8 `test_reference_null_at_or_after_data_end`.
3. **Several swaps of one transaction in our pool.** Gas and builder payments must be split across them
   so they sum to the transaction's cost, and an episode's closer must be the swap that moved the price
   furthest toward Binance. Tests: Task 10 `test_costs_split_by_notional_within_tx`, Task 12
   `test_closer_is_swap_moving_furthest_toward_cex`.
4. **Zero-notional swaps** (`amount_usdc == 0`). bp must be null, not ±inf, and must not distort
   weighted means. Test: Task 9 `test_zero_notional_gives_null_bp`.
5. **The top-bot set changes after editing the label CSV.** Analysis must refuse to run with missing
   transfer or other-log data for a top bot, naming the command to run, instead of silently treating
   the bot as paying nothing. Tests: Task 6 `test_bot_tx_logs_current`, Task 7
   `test_load_bot_transfers_names_missing_bots`.

## File map

| File | Responsibility | Task |
|---|---|---|
| `src/uniswap_lp_economics/validate.py` (modify) | Hash-drift check in `require_validated`; `file_hash`; replay loop on `replay.py`; `write_report` stem/title; `git_commit` | 1, 2, 13, 15 |
| `src/uniswap_lp_economics/tickbook.py` (modify) | `nearest_initialized` | 2 |
| `src/uniswap_lp_economics/replay.py` | Public replay: rows, `apply_event`, swap pre-states, block starts | 2 |
| `scripts/make_fixture.py` (modify), `tests/fixtures/*` | Fixture keeps every event column | 2 |
| `src/uniswap_lp_economics/v3math.py` | (unchanged; used) | — |
| `src/uniswap_lp_economics/v3swap.py` | Exact V3 swap, swap-event check, arbitrage-to-price | 3, 4 |
| `labels/addresses.csv`, `src/uniswap_lp_economics/flows.py` | Curated labels, swap labelling, top bots, coverage | 5 |
| `src/uniswap_lp_economics/config.py` (modify) | New constants | 5, 6, 8, 15 |
| `src/uniswap_lp_economics/data/blocks.py` | BigQuery: blocks; other logs in top-bot txs | 6 |
| `src/uniswap_lp_economics/data/transfers.py` | Alchemy internal transfers per bot | 7 |
| `src/uniswap_lp_economics/cli.py` (modify) | `fetch-blocks`, `fetch-transfers`, `analyze` | 7, 15 |
| `src/uniswap_lp_economics/align.py` | As-of reference prices | 8 |
| `src/uniswap_lp_economics/markouts.py` | Markout columns, tables, day bootstrap | 9 |
| `src/uniswap_lp_economics/arbprofit.py` | Tx scope, costs, coinbase, bot profit, waterfall | 10 |
| `src/uniswap_lp_economics/discovery.py` | Block series, basis, episodes, lead-lag, available vs captured | 11, 12 |
| `src/uniswap_lp_economics/checks.py` | A1–A6 | 13 |
| `src/uniswap_lp_economics/report.py`, `figures.py` | Tables, summary.json, charts | 14 |
| `src/uniswap_lp_economics/analyze.py` | Load inputs, compose, write `results/` | 15 |
| `results/`, `data/processed/` | Outputs (results committed; processed git-ignored under `/data/`) | 16 |
| `docs/methodology.md`, `README.md` | Definitions, findings, limitations | 17 |

---

### Task 1: Hash-drift check in `require_validated`

Carry-over item 1. `require_validated()` must refuse to run when any validated `interim/*` file has
changed or disappeared since `ulpe validate` ran.

**Files:**
- Modify: `src/uniswap_lp_economics/validate.py` (`require_validated`, rename `_file_hash` → `file_hash`)
- Test: `tests/test_validate.py`

**Interfaces:**
- Produces: `validate.file_hash(path: Path) -> str` (first 16 hex chars of SHA-256), and
  `validate.require_validated(report_dir: Path = config.VALIDATION_DIR, data_dir: Path = config.DATA_DIR) -> None`.

- [ ] **Step 1: Replace the old report test and add the drift tests**

In `tests/test_validate.py`, replace `test_report_and_require_validated` with the block below and add
the three new tests after it:

```python
def _validated(tmp_path: Path) -> tuple[Path, Path]:
    """A PASS report whose hashes match the files in a small data dir; returns (report, data)."""
    data = tmp_path / "data"
    (data / "interim").mkdir(parents=True)
    (data / "raw").mkdir()
    (data / "raw" / "tickbook_snapshot.parquet").write_bytes(b"ticks")
    (data / "raw" / "snapshot_meta.json").write_bytes(b"{}")
    (data / "interim" / "swaps.parquet").write_bytes(b"swaps v1")
    report_dir = tmp_path / "report"
    write_report(
        [CheckResult("C1", True, {"n": 1}, [])],
        report_dir,
        {"input_sha256_16": input_hashes(data / "raw", data / "interim")},
    )
    return report_dir, data


def test_report_and_require_validated(tmp_path: Path) -> None:
    report_dir, data = _validated(tmp_path)
    require_validated(report_dir, data)
    assert "C1" in (report_dir / "validation_report.md").read_text()
    write_report(
        [CheckResult("C1", True, {}, []), CheckResult("C2", False, {}, [{"x": 1}])], report_dir, {}
    )
    with pytest.raises(RuntimeError, match="FAIL"):
        require_validated(report_dir, data)
    assert json.loads((report_dir / "validation_report.json").read_text())["status"] == "FAIL"


def test_require_validated_detects_changed_interim_file(tmp_path: Path) -> None:
    report_dir, data = _validated(tmp_path)
    (data / "interim" / "swaps.parquet").write_bytes(b"swaps v2")
    with pytest.raises(RuntimeError, match="interim/swaps.parquet changed"):
        require_validated(report_dir, data)


def test_require_validated_detects_missing_interim_file(tmp_path: Path) -> None:
    report_dir, data = _validated(tmp_path)
    (data / "interim" / "swaps.parquet").unlink()
    with pytest.raises(RuntimeError, match=r"interim/swaps.parquet .*missing"):
        require_validated(report_dir, data)


def test_require_validated_rejects_report_without_hashes(tmp_path: Path) -> None:
    write_report([CheckResult("C1", True, {}, [])], tmp_path, {})
    with pytest.raises(RuntimeError, match="no interim file hashes"):
        require_validated(tmp_path, tmp_path)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_validate.py -q`
Expected: the four tests above FAIL (`require_validated` takes one argument / does not check hashes).

- [ ] **Step 3: Implement**

In `src/uniswap_lp_economics/validate.py`, rename `_file_hash` to `file_hash` (update its use in
`input_hashes`) and replace `require_validated` with:

```python
def require_validated(
    report_dir: Path = config.VALIDATION_DIR, data_dir: Path = config.DATA_DIR
) -> None:
    """Refuse to analyse unless validation passed on exactly the interim files now on disk."""
    path = report_dir / "validation_report.json"
    if not path.exists():
        raise RuntimeError(f"{path} missing; run `ulpe validate` first")
    report = json.loads(path.read_text())
    status = report["status"]
    if status != "PASS":
        raise RuntimeError(f"validation status is {status}; fix the data before analysis")
    hashes: dict[str, str] = report.get("input_sha256_16", {})
    interim = {k: v for k, v in hashes.items() if k.startswith("interim/")}
    if not interim:
        raise RuntimeError(
            "validation report lists no interim file hashes; run `ulpe validate` again"
        )
    for rel, expected in sorted(interim.items()):
        p = data_dir / rel
        if not p.exists():
            raise RuntimeError(
                f"{rel} was validated but is now missing; run `ulpe build` and `ulpe validate`"
            )
        if file_hash(p) != expected:
            raise RuntimeError(f"{rel} changed since validation; run `ulpe validate` again")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_validate.py -q`
Expected: PASS.

- [ ] **Step 5: Check against the real report** (real data)

Run: `uv run python -c "from uniswap_lp_economics.validate import require_validated; require_validated(); print('ok')"`
Expected: `ok` (the committed report's hashes match the data on disk). If it raises "changed since
validation", stop and report it: the data on disk is not what was validated.

- [ ] **Step 6: Lint, type-check, full tests, commit, push**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/validate.py tests/test_validate.py
git commit -m "require_validated: refuse to run when validated interim files changed"
git push
```

---

### Task 2: Public replay helper

Carry-over item 2. One public module replays events; `validate.replay` is refactored onto it with
unchanged C1/C2 results. The real-data fixture is regenerated with every event column so later tasks
can rebuild swaps and re-simulate them.

**Files:**
- Create: `src/uniswap_lp_economics/replay.py`, `tests/test_replay.py`
- Modify: `src/uniswap_lp_economics/tickbook.py` (add `nearest_initialized`), `tests/test_tickbook.py`
- Modify: `src/uniswap_lp_economics/validate.py` (`replay` loop)
- Modify: `scripts/make_fixture.py`; regenerate `tests/fixtures/*`
- Modify: `tests/test_integration.py`

**Interfaces:**
- Produces:
  - `TickBook.nearest_initialized(tick: int, lte: bool) -> int | None`
  - `replay.ReplayRow` (NamedTuple: `block_number, log_index, event, tick, sqrt_price_x96, liquidity,
    tick_lower, tick_upper, amount, fee_protocol0_new, fee_protocol1_new, amount0, amount1`; all but
    the first three are `int | None`)
  - `replay.REPLAY_COLUMNS: list[str]`
  - `replay.iter_event_rows(events: pl.DataFrame) -> Iterator[ReplayRow]`
  - `replay.required(row: ReplayRow, name: str) -> int`
  - `replay.apply_event(book: TickBook, row: ReplayRow, fee_protocol: int) -> int`
  - `replay.iter_swaps_with_pre_state(events, book, fee_protocol) -> Iterator[ReplayRow]`
  - `replay.iter_block_starts(events, book, fee_protocol, first_block: int, last_block: int) -> Iterator[int]`
  - Fixture `tests/fixtures/fixture_events.parquet` with every column of `interim/events.parquet`.

- [ ] **Step 1: Test `nearest_initialized`**

Append to `tests/test_tickbook.py` (it already imports `TickBook`; add
`from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at` if missing):

```python
def test_nearest_initialized() -> None:
    b = TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0)
    b.apply_mint(-20, 30, 5)
    assert b.nearest_initialized(30, lte=True) == 30
    assert b.nearest_initialized(29, lte=True) == -20
    assert b.nearest_initialized(-21, lte=True) is None
    assert b.nearest_initialized(-20, lte=False) == -20
    assert b.nearest_initialized(-19, lte=False) == 30
    assert b.nearest_initialized(31, lte=False) is None
```

- [ ] **Step 2: Write the replay tests**

Create `tests/test_replay.py`:

```python
import polars as pl
import pytest

from uniswap_lp_economics.replay import (
    ReplayRow,
    apply_event,
    iter_block_starts,
    iter_event_rows,
    iter_swaps_with_pre_state,
    required,
)
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at

SCHEMA = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "event": pl.String,
    "tick": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "liquidity": pl.Int128,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "amount": pl.Int128,
    "fee_protocol0_new": pl.Int64,
    "fee_protocol1_new": pl.Int64,
}


def ev(block: int, idx: int, event: str, **kw: int) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(SCHEMA)
    row.update(block_number=block, log_index=idx, event=event, **kw)
    return row


def events(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA)


def book() -> TickBook:
    b = TickBook(tick=50, sqrt_price_x96=sqrt_at(50), liquidity=0)
    b.apply_mint(-100, 100, 1000)
    return b


def test_iter_event_rows_sorts_and_fills_missing_columns() -> None:
    e = events(
        [
            ev(2, 0, "swap", tick=10, sqrt_price_x96=sqrt_at(10), liquidity=1000),
            ev(1, 5, "mint", tick_lower=0, tick_upper=10, amount=1),
        ]
    )
    rows = list(iter_event_rows(e))
    assert [(r.block_number, r.log_index) for r in rows] == [(1, 5), (2, 0)]
    assert rows[0].amount0 is None and rows[1].amount1 is None


def test_apply_event_returns_new_fee_protocol() -> None:
    e = events([ev(1, 0, "set_fee_protocol", fee_protocol0_new=4, fee_protocol1_new=5)])
    assert apply_event(book(), next(iter_event_rows(e)), 0) == 4 + (5 << 4)


def test_apply_event_rejects_swap_without_price() -> None:
    row = ReplayRow(1, 0, "swap", None, None, None, None, None, None, None, None, None, None)
    with pytest.raises(ValueError, match="sqrt_price_x96"):
        apply_event(book(), row, 0)
    with pytest.raises(ValueError, match="no tick"):
        required(row, "tick")


def test_swaps_are_yielded_in_pre_state() -> None:
    e = events(
        [
            ev(1, 0, "swap", tick=150, sqrt_price_x96=sqrt_at(150) + 1, liquidity=0),
            ev(1, 1, "swap", tick=60, sqrt_price_x96=sqrt_at(60) + 1, liquidity=1000),
        ]
    )
    b = book()
    seen = [(r.log_index, b.tick, b.liquidity) for r in iter_swaps_with_pre_state(e, b, 0)]
    assert seen == [(0, 50, 1000), (1, 150, 0)]
    assert (b.tick, b.liquidity) == (60, 1000)


def test_block_starts_cover_every_block_and_end_state() -> None:
    e = events(
        [
            ev(11, 0, "swap", tick=150, sqrt_price_x96=sqrt_at(150) + 1, liquidity=0),
            ev(13, 0, "mint", tick_lower=100, tick_upper=200, amount=7),
        ]
    )
    b = book()
    states = {blk: (b.tick, b.liquidity) for blk in iter_block_starts(e, b, 0, 10, 13)}
    assert states == {10: (50, 1000), 11: (50, 1000), 12: (150, 0), 13: (150, 0), 14: (150, 7)}


def test_block_starts_reject_events_outside_range() -> None:
    e = events([ev(20, 0, "mint", tick_lower=0, tick_upper=10, amount=1)])
    with pytest.raises(ValueError, match="after last_block"):
        list(iter_block_starts(e, book(), 0, 10, 13))
    with pytest.raises(ValueError, match="before first_block"):
        list(iter_block_starts(e, book(), 0, 21, 22))
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_replay.py tests/test_tickbook.py -q`
Expected: FAIL (no module `replay`; no `nearest_initialized`).

- [ ] **Step 4: Implement `nearest_initialized`**

In `src/uniswap_lp_economics/tickbook.py`, change the import to
`from bisect import bisect_left, bisect_right, insort` and add to `TickBook`:

```python
    def nearest_initialized(self, tick: int, lte: bool) -> int | None:
        """Largest initialized tick <= tick (lte) or smallest initialized tick >= tick (not lte)."""
        if lte:
            i = bisect_right(self._sorted, tick)
            return self._sorted[i - 1] if i else None
        i = bisect_left(self._sorted, tick)
        return self._sorted[i] if i < len(self._sorted) else None
```

- [ ] **Step 5: Implement `replay.py`**

Create `src/uniswap_lp_economics/replay.py`:

```python
"""Public event replay: drive a TickBook through pool events in (block, log_index) order.

The generators mutate the TickBook they are given and hand control back while it holds a
well-defined state. Read what you need from it before resuming the iteration.
"""

from collections.abc import Iterator
from typing import NamedTuple

import polars as pl

from uniswap_lp_economics.tickbook import TickBook


class ReplayRow(NamedTuple):
    block_number: int
    log_index: int
    event: str
    tick: int | None
    sqrt_price_x96: int | None
    liquidity: int | None
    tick_lower: int | None
    tick_upper: int | None
    amount: int | None
    fee_protocol0_new: int | None
    fee_protocol1_new: int | None
    amount0: int | None
    amount1: int | None


REPLAY_COLUMNS = list(ReplayRow._fields)
_INT128 = {"sqrt_price_x96", "liquidity", "amount", "amount0", "amount1"}


def iter_event_rows(events: pl.DataFrame) -> Iterator[ReplayRow]:
    """Rows in (block_number, log_index) order; columns missing from `events` come back as None."""
    missing = [c for c in REPLAY_COLUMNS if c not in events.columns]
    filled = events.with_columns(
        pl.lit(None, dtype=pl.Int128 if c in _INT128 else pl.Int64).alias(c) for c in missing
    )
    for r in filled.sort("block_number", "log_index").select(REPLAY_COLUMNS).iter_rows():
        yield ReplayRow(*r)


def required(row: ReplayRow, name: str) -> int:
    """The named integer field of `row`, or a ValueError saying which event lacks it."""
    value = getattr(row, name)
    if value is None:
        raise ValueError(
            f"{row.event} at block {row.block_number} log {row.log_index} has no {name}"
        )
    return int(value)


def apply_event(book: TickBook, row: ReplayRow, fee_protocol: int) -> int:
    """Apply one event to `book` in place; return the packed feeProtocol in force afterwards."""
    if row.event == "mint":
        book.apply_mint(
            required(row, "tick_lower"), required(row, "tick_upper"), required(row, "amount")
        )
    elif row.event == "burn":
        book.apply_burn(
            required(row, "tick_lower"), required(row, "tick_upper"), required(row, "amount")
        )
    elif row.event == "swap":
        book.apply_swap(required(row, "sqrt_price_x96"), required(row, "tick"))
    elif row.event == "set_fee_protocol":
        return required(row, "fee_protocol0_new") + (required(row, "fee_protocol1_new") << 4)
    return fee_protocol


def iter_swaps_with_pre_state(
    events: pl.DataFrame, book: TickBook, fee_protocol: int
) -> Iterator[ReplayRow]:
    """Yield every swap while `book` still holds the state just before that swap."""
    for row in iter_event_rows(events):
        if row.event == "swap":
            yield row
        fee_protocol = apply_event(book, row, fee_protocol)


def iter_block_starts(
    events: pl.DataFrame, book: TickBook, fee_protocol: int, first_block: int, last_block: int
) -> Iterator[int]:
    """Yield every block number in [first_block, last_block + 1] while `book` holds the pool state
    at that block's start: after all events of earlier blocks, before any of its own.

    The final yield (last_block + 1) is the state at the end of last_block. Events outside
    [first_block, last_block] raise ValueError.
    """
    rows = iter_event_rows(events)
    pending = next(rows, None)
    if pending is not None and pending.block_number < first_block:
        raise ValueError(
            f"event in block {pending.block_number} is before first_block {first_block}"
        )
    for block in range(first_block, last_block + 1):
        yield block
        while pending is not None and pending.block_number == block:
            fee_protocol = apply_event(book, pending, fee_protocol)
            pending = next(rows, None)
    if pending is not None:
        raise ValueError(f"event in block {pending.block_number} is after last_block {last_block}")
    yield last_block + 1
```

- [ ] **Step 6: Refactor `validate.replay` onto it**

In `src/uniswap_lp_economics/validate.py` add
`from uniswap_lp_economics.replay import apply_event, iter_event_rows, required`, delete the local
`cols` list, and replace the `for blk, idx, kind, ... in (...).iter_rows():` loop (up to and including
its body) with:

```python
    for row in iter_event_rows(events):
        flush(row.block_number)
        fee_protocol = apply_event(book, row, fee_protocol)
        if row.event != "swap":
            continue
        n_swaps += 1
        blk, idx = row.block_number, row.log_index
        sqrt, tick = required(row, "sqrt_price_x96"), required(row, "tick")
        liq = required(row, "liquidity")
        if book.liquidity != liq:
            c1_count += 1
            if len(c1_bad) < MAX_LISTED:
                c1_bad.append(
                    {"block": blk, "log_index": idx, "expected": liq, "replayed": book.liquidity}
                )
            book.liquidity = liq  # resync so one bug doesn't cascade into every later swap
        ok, is_boundary = c2_tick_ok(sqrt, tick)
        boundary += is_boundary
        if not ok:
            c2_count += 1
            if len(c2_bad) < MAX_LISTED:
                c2_bad.append({"block": blk, "log_index": idx, "tick": tick, "sqrt_price_x96": sqrt})
```

Leave the code after the loop (`flush(None)`, the `CheckResult`s) unchanged.

- [ ] **Step 7: Run the unit tests**

Run: `uv run pytest tests/test_replay.py tests/test_tickbook.py tests/test_validate.py tests/test_integration.py -q`
Expected: PASS (validate's own tests prove C1/C2 behaviour is unchanged).

- [ ] **Step 8: Keep every event column in the fixture and regenerate it** (real data)

In `scripts/make_fixture.py`, delete the `COLS` list and the line `events = events.select(COLS)`, so
the fixture keeps every column of `interim/events.parquet`. Then run:

```bash
uv run python scripts/make_fixture.py
```

Expected: `fixture: 400 events, 513 ticks`. Check the size: `ls -l tests/fixtures` (the events file
must stay under 1 MB).

- [ ] **Step 9: Add the block-start integration test**

In `tests/test_integration.py`, add a loader and a test (new imports go at the top of the file with the existing ones; keep the existing test and switch it to the
loader):

```python
import polars as pl

from uniswap_lp_economics.replay import iter_block_starts


def _fixture() -> tuple[dict[str, int], TickBook, pl.DataFrame]:
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    book = TickBook.from_snapshot(read_exact(FIX / "fixture_ticks.parquet"), meta)
    return meta, book, read_exact(FIX / "fixture_events.parquet")


def test_block_starts_end_at_last_swap_price() -> None:
    meta, book, events = _fixture()
    first = int(meta["block"]) + 1
    last = int(events["block_number"].max())  # type: ignore[arg-type]
    seen = list(iter_block_starts(events, book, int(meta["fee_protocol"]), first, last))
    assert seen == list(range(first, last + 2))
    last_swap = events.filter(pl.col("event") == "swap").sort("block_number", "log_index").tail(1)
    assert book.sqrt_price_x96 == last_swap["sqrt_price_x96"].item()
```

- [ ] **Step 10: Lint, type-check, full tests, commit, push**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/replay.py src/uniswap_lp_economics/tickbook.py src/uniswap_lp_economics/validate.py scripts/make_fixture.py tests/
git commit -m "Add public replay helper; validate replays through it; fixture keeps all columns"
git push
```

---

### Task 3: Exact V3 swap simulation (`v3swap.py`)

An exact-integer port of V3's `SqrtPriceMath`, `SwapMath.computeSwapStep`,
`TickBitmap.nextInitializedTickWithinOneWord` (answered from the TickBook) and the pool's swap loop,
exact-input only. Plus a helper that re-simulates a historical swap for check A1 (Ruling 2).

**Files:**
- Create: `src/uniswap_lp_economics/v3swap.py`, `tests/test_v3swap.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- Consumes: `TickBook` (`sqrt_price_x96`, `tick`, `liquidity`, `liquidity_net`,
  `nearest_initialized`), `v3math` constants and `get_sqrt_ratio_at_tick` / `get_tick_at_sqrt_ratio`,
  `replay.iter_swaps_with_pre_state`, `replay.required`.
- Produces:
  - `get_amount0_delta(sqrt_a, sqrt_b, liquidity, round_up) -> int`,
    `get_amount1_delta(...) -> int`
  - `next_sqrt_price_from_input(sqrt_price, liquidity, amount_in, zero_for_one) -> int`
  - `compute_swap_step(sqrt_current, sqrt_target, liquidity, amount_remaining, fee_pips) -> tuple[int, int, int, int]`
    returning `(sqrt_next, amount_in, amount_out, fee)`
  - `next_initialized_tick_within_one_word(book, tick, lte, tick_spacing=TICK_SPACING) -> tuple[int, bool]`
  - `SwapResult(amount_in, amount_out, fee, sqrt_price_x96, tick, liquidity)` (frozen dataclass; ints)
  - `swap_exact_input(book, zero_for_one, amount_in, sqrt_price_limit_x96=None, fee_pips=FEE_PIPS, tick_spacing=TICK_SPACING) -> SwapResult`
  - `SwapCheck(sqrt_rel_err: float, out_abs_err: int, out_expected: int, exact: bool)`,
    `check_swap_event(book, amount0, amount1, sqrt_price_x96, fee_pips=FEE_PIPS) -> SwapCheck | None`,
    `swap_check_ok(c: SwapCheck) -> bool`

- [ ] **Step 1: Write the tests**

Create `tests/test_v3swap.py`:

> **Note:** the `swap_check_ok` tests below predate the two amendments of Ruling 2 made during implementation; the Rulings section is authoritative.

```python
import random

import pytest

from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import Q96
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import (
    SwapCheck,
    compute_swap_step,
    get_amount0_delta,
    get_amount1_delta,
    next_initialized_tick_within_one_word,
    swap_check_ok,
    swap_exact_input,
)

L = 10**18


def test_amount_deltas_hand_vectors() -> None:
    assert get_amount1_delta(Q96, 2 * Q96, L, True) == L
    assert get_amount1_delta(2 * Q96, Q96, L, False) == L
    assert get_amount0_delta(Q96, 2 * Q96, L, True) == L // 2
    assert get_amount0_delta(2 * Q96, Q96, L, False) == L // 2


def test_swap_step_reaching_target_hand_vector() -> None:
    # 0.05% fee on 5e17 in, rounded up: ceil(5e17 * 500 / 999500) = 250125062531266.
    assert compute_swap_step(2 * Q96, Q96, L, L, 500) == (Q96, L // 2, L, 250_125_062_531_266)


def test_swap_step_partial_hand_vector() -> None:
    sqrt_next, amount_in, amount_out, fee = compute_swap_step(Q96, 2 * Q96, L, 5 * 10**17, 500)
    assert sqrt_next == 118_822_436_730_767_940_305_917_539_516
    assert (amount_in, fee) == (499_750_000_000_000_000, 250_000_000_000_000)
    assert amount_out == 333_222_203_700_616_769


def _reference_next(initialized: set[int], tick: int, lte: bool) -> tuple[int, bool]:
    """Literal port of TickBitmap.nextInitializedTickWithinOneWord over an explicit bitmap."""
    spacing = 10
    bitmap: dict[int, int] = {}
    for t in initialized:
        c = t // spacing
        bitmap[c >> 8] = bitmap.get(c >> 8, 0) | (1 << (c & 255))
    compressed = tick // spacing
    if lte:
        word, bit = compressed >> 8, compressed & 255
        masked = bitmap.get(word, 0) & ((1 << bit) - 1 + (1 << bit))
        if masked:
            return (compressed - (bit - (masked.bit_length() - 1))) * spacing, True
        return (compressed - bit) * spacing, False
    word, bit = (compressed + 1) >> 8, (compressed + 1) & 255
    masked = bitmap.get(word, 0) & ~((1 << bit) - 1)
    if masked:
        lsb = (masked & -masked).bit_length() - 1
        return (compressed + 1 + (lsb - bit)) * spacing, True
    return (compressed + 1 + (255 - bit)) * spacing, False


def test_next_initialized_tick_matches_bitmap_reference() -> None:
    rng = random.Random(7)
    ticks = sorted({rng.randrange(-600, 600) * 10 for _ in range(40)})
    book = TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0)
    for lo, hi in zip(ticks[::2], ticks[1::2], strict=False):
        book.apply_mint(lo, hi, 1)
    init = set(book.initialized_ticks())
    for _ in range(2000):
        t = rng.randrange(-7000, 7000)
        for lte in (True, False):
            assert next_initialized_tick_within_one_word(book, t, lte) == _reference_next(
                init, t, lte
            ), (t, lte)


def two_range_book() -> TickBook:
    b = TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0)
    b.apply_mint(-10, 10, L)  # active at tick 0
    b.apply_mint(10, 20, 2 * L)
    return b


def test_swap_up_crosses_tick_and_picks_up_liquidity() -> None:
    b = two_range_book()
    to_10 = get_amount1_delta(sqrt_at(0), sqrt_at(10), L, True)
    amount = to_10 + to_10 // 4  # crosses 10, stops well before 20
    r = swap_exact_input(b, zero_for_one=False, amount_in=amount)
    assert 10 <= r.tick < 20
    assert r.liquidity == 2 * L
    assert r.amount_in == amount
    expected_out = get_amount0_delta(sqrt_at(0), sqrt_at(10), L, False) + get_amount0_delta(
        sqrt_at(10), r.sqrt_price_x96, 2 * L, False
    )
    assert r.amount_out == expected_out
    assert (b.tick, b.sqrt_price_x96, b.liquidity) == (0, sqrt_at(0), L)  # book untouched


def test_swap_down_crosses_tick_and_drops_liquidity() -> None:
    b = two_range_book()
    b.apply_swap(sqrt_at(15), 15)
    assert b.liquidity == 2 * L
    to_10 = get_amount0_delta(sqrt_at(10), sqrt_at(15), 2 * L, True)
    r = swap_exact_input(b, zero_for_one=True, amount_in=to_10 + to_10 // 4)
    assert 0 <= r.tick < 10
    assert r.liquidity == L
    expected_out = get_amount1_delta(sqrt_at(10), sqrt_at(15), 2 * L, False) + get_amount1_delta(
        r.sqrt_price_x96, sqrt_at(10), L, False
    )
    assert r.amount_out == expected_out


def test_swap_stops_at_price_limit() -> None:
    b = two_range_book()
    limit = sqrt_at(5)
    r = swap_exact_input(b, False, 10**30, sqrt_price_limit_x96=limit)
    assert r.sqrt_price_x96 == limit
    assert r.amount_in == get_amount1_delta(sqrt_at(0), limit, L, True) + r.fee
    assert r.amount_in < 10**30


def test_swap_rejects_limit_on_wrong_side_and_empty_input() -> None:
    b = two_range_book()
    with pytest.raises(ValueError, match="SPL"):
        swap_exact_input(b, True, 1, sqrt_price_limit_x96=sqrt_at(5))
    with pytest.raises(ValueError, match="positive"):
        swap_exact_input(b, True, 0)


def test_swap_check_tolerance() -> None:
    assert swap_check_ok(SwapCheck(0.0, 2, 10, False))
    assert not swap_check_ok(SwapCheck(0.0, 3, 10, False))
    assert swap_check_ok(SwapCheck(0.0, 3, 10**10, False))
    assert not swap_check_ok(SwapCheck(1e-8, 0, 10, False))
```

Add to `tests/test_integration.py` (new imports at the top of the file):

```python
from uniswap_lp_economics.replay import iter_swaps_with_pre_state, required
from uniswap_lp_economics.v3swap import check_swap_event, swap_check_ok


def test_v3swap_reproduces_fixture_swaps() -> None:
    meta, book, events = _fixture()
    checked = exact = 0
    for row in iter_swaps_with_pre_state(events, book, int(meta["fee_protocol"])):
        c = check_swap_event(
            book,
            required(row, "amount0"),
            required(row, "amount1"),
            required(row, "sqrt_price_x96"),
        )
        if c is None:
            continue
        checked += 1
        exact += c.exact
        assert swap_check_ok(c), (row.block_number, row.log_index, c)
    assert checked > 300
    assert exact > 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_v3swap.py tests/test_integration.py -q`
Expected: FAIL (no module `v3swap`).

- [ ] **Step 3: Implement**

Create `src/uniswap_lp_economics/v3swap.py`:

> **Note:** the `SwapCheck` / `swap_check_ok` code below predates the two amendments of Ruling 2 made during implementation; the Rulings section is authoritative.

```python
"""Exact-integer Uniswap V3 swap simulation over a TickBook (exact input only).

Ports SqrtPriceMath, SwapMath.computeSwapStep, TickBitmap.nextInitializedTickWithinOneWord and the
pool's swap loop. Python ints are unbounded, so Solidity's uint256 overflow branches are reproduced
explicitly where they change the result. Nothing here mutates the TickBook.
"""

from dataclasses import dataclass

from uniswap_lp_economics.config import FEE_PIPS, TICK_SPACING
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import (
    MAX_SQRT_RATIO,
    MAX_TICK,
    MIN_SQRT_RATIO,
    MIN_TICK,
    Q96,
    get_sqrt_ratio_at_tick,
    get_tick_at_sqrt_ratio,
)

_U256 = 2**256
_PIPS = 1_000_000
A1_SQRT_REL_TOL = 1e-9
A1_OUT_ABS_TOL = 2
A1_OUT_REL_TOL = 1e-9


def mul_div(a: int, b: int, d: int) -> int:
    return a * b // d


def mul_div_rounding_up(a: int, b: int, d: int) -> int:
    q, r = divmod(a * b, d)
    return q + (1 if r else 0)


def div_rounding_up(a: int, b: int) -> int:
    return -(-a // b)


def get_amount0_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    """Token0 (USDC) between two sqrt prices: L * 2^96 * (b - a) / (a * b)."""
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    numerator1 = liquidity << 96
    numerator2 = sqrt_b - sqrt_a
    if round_up:
        return div_rounding_up(mul_div_rounding_up(numerator1, numerator2, sqrt_b), sqrt_a)
    return mul_div(numerator1, numerator2, sqrt_b) // sqrt_a


def get_amount1_delta(sqrt_a: int, sqrt_b: int, liquidity: int, round_up: bool) -> int:
    """Token1 (WETH) between two sqrt prices: L * (b - a) / 2^96."""
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    if round_up:
        return mul_div_rounding_up(liquidity, sqrt_b - sqrt_a, Q96)
    return mul_div(liquidity, sqrt_b - sqrt_a, Q96)


def next_sqrt_price_from_input(
    sqrt_price: int, liquidity: int, amount_in: int, zero_for_one: bool
) -> int:
    """SqrtPriceMath.getNextSqrtPriceFromInput."""
    if liquidity <= 0:
        raise ValueError("liquidity must be positive")
    if amount_in == 0:
        return sqrt_price
    if zero_for_one:  # getNextSqrtPriceFromAmount0RoundingUp(add = true)
        numerator1 = liquidity << 96
        product = amount_in * sqrt_price
        if product < _U256 and numerator1 + product < _U256:
            return mul_div_rounding_up(numerator1, sqrt_price, numerator1 + product)
        return div_rounding_up(numerator1, numerator1 // sqrt_price + amount_in)
    return sqrt_price + (amount_in << 96) // liquidity  # getNextSqrtPriceFromAmount1RoundingDown


def compute_swap_step(
    sqrt_current: int, sqrt_target: int, liquidity: int, amount_remaining: int, fee_pips: int
) -> tuple[int, int, int, int]:
    """SwapMath.computeSwapStep for exact input: (sqrt_next, amount_in, amount_out, fee)."""
    zero_for_one = sqrt_current >= sqrt_target
    remaining_less_fee = mul_div(amount_remaining, _PIPS - fee_pips, _PIPS)
    if zero_for_one:
        amount_in = get_amount0_delta(sqrt_target, sqrt_current, liquidity, True)
    else:
        amount_in = get_amount1_delta(sqrt_current, sqrt_target, liquidity, True)
    if remaining_less_fee >= amount_in:
        sqrt_next = sqrt_target
    else:
        sqrt_next = next_sqrt_price_from_input(
            sqrt_current, liquidity, remaining_less_fee, zero_for_one
        )
    reached = sqrt_next == sqrt_target
    if zero_for_one:
        if not reached:
            amount_in = get_amount0_delta(sqrt_next, sqrt_current, liquidity, True)
        amount_out = get_amount1_delta(sqrt_next, sqrt_current, liquidity, False)
    else:
        if not reached:
            amount_in = get_amount1_delta(sqrt_current, sqrt_next, liquidity, True)
        amount_out = get_amount0_delta(sqrt_current, sqrt_next, liquidity, False)
    if reached:
        fee = mul_div_rounding_up(amount_in, fee_pips, _PIPS - fee_pips)
    else:
        fee = amount_remaining - amount_in
    return sqrt_next, amount_in, amount_out, fee


def next_initialized_tick_within_one_word(
    book: TickBook, tick: int, lte: bool, tick_spacing: int = TICK_SPACING
) -> tuple[int, bool]:
    """TickBitmap.nextInitializedTickWithinOneWord, answered from the book's initialized ticks."""
    compressed = tick // tick_spacing  # floor, as V3 does for negative ticks
    if lte:
        word_start = (compressed - (compressed & 255)) * tick_spacing
        t = book.nearest_initialized(compressed * tick_spacing, lte=True)
        if t is not None and t >= word_start:
            return t, True
        return word_start, False
    nxt = compressed + 1
    word_end = (nxt + 255 - (nxt & 255)) * tick_spacing
    t = book.nearest_initialized(nxt * tick_spacing, lte=False)
    if t is not None and t <= word_end:
        return t, True
    return word_end, False


@dataclass(frozen=True)
class SwapResult:
    amount_in: int  # input token consumed, fee included
    amount_out: int  # output token paid out (positive)
    fee: int  # input-token fee, part of amount_in
    sqrt_price_x96: int
    tick: int
    liquidity: int


def swap_exact_input(
    book: TickBook,
    zero_for_one: bool,
    amount_in: int,
    sqrt_price_limit_x96: int | None = None,
    fee_pips: int = FEE_PIPS,
    tick_spacing: int = TICK_SPACING,
) -> SwapResult:
    """UniswapV3Pool.swap for an exact input, from the book's current state (not mutated)."""
    if amount_in <= 0:
        raise ValueError(f"amount_in must be positive, got {amount_in}")
    sqrt_price, tick, liquidity = book.sqrt_price_x96, book.tick, book.liquidity
    if sqrt_price_limit_x96 is None:
        limit = MIN_SQRT_RATIO + 1 if zero_for_one else MAX_SQRT_RATIO - 1
    else:
        limit = sqrt_price_limit_x96
    if zero_for_one:
        valid = MIN_SQRT_RATIO < limit < sqrt_price
    else:
        valid = sqrt_price < limit < MAX_SQRT_RATIO
    if not valid:
        raise ValueError("sqrt_price_limit_x96 is on the wrong side of the current price (SPL)")

    remaining, out, fees = amount_in, 0, 0
    while remaining != 0 and sqrt_price != limit:
        start = sqrt_price
        tick_next, initialized = next_initialized_tick_within_one_word(
            book, tick, zero_for_one, tick_spacing
        )
        tick_next = max(MIN_TICK, min(MAX_TICK, tick_next))
        sqrt_at_next = get_sqrt_ratio_at_tick(tick_next)
        if zero_for_one:
            target = limit if sqrt_at_next < limit else sqrt_at_next
        else:
            target = limit if sqrt_at_next > limit else sqrt_at_next
        sqrt_price, step_in, step_out, step_fee = compute_swap_step(
            sqrt_price, target, liquidity, remaining, fee_pips
        )
        remaining -= step_in + step_fee
        out += step_out
        fees += step_fee
        if sqrt_price == sqrt_at_next:
            if initialized:
                net = book.liquidity_net[tick_next]
                liquidity += -net if zero_for_one else net
                if liquidity < 0:
                    raise ValueError(f"liquidity went negative crossing tick {tick_next}")
            tick = tick_next - 1 if zero_for_one else tick_next
        elif sqrt_price != start:
            tick = get_tick_at_sqrt_ratio(sqrt_price)
    return SwapResult(amount_in - remaining, out, fees, sqrt_price, tick, liquidity)


@dataclass(frozen=True)
class SwapCheck:
    sqrt_rel_err: float
    out_abs_err: int
    out_expected: int
    exact: bool


def check_swap_event(
    book: TickBook, amount0: int, amount1: int, sqrt_price_x96: int, fee_pips: int = FEE_PIPS
) -> SwapCheck | None:
    """Re-simulate a historical swap from `book` (its pre-swap state) with the event's input.

    Returns None when the swap has no input (neither amount is positive).
    """
    if amount0 > 0:
        zero_for_one, amount_in, out_expected = True, amount0, -amount1
    elif amount1 > 0:
        zero_for_one, amount_in, out_expected = False, amount1, -amount0
    else:
        return None
    r = swap_exact_input(book, zero_for_one, amount_in, fee_pips=fee_pips)
    return SwapCheck(
        sqrt_rel_err=abs(r.sqrt_price_x96 - sqrt_price_x96) / sqrt_price_x96,
        out_abs_err=abs(r.amount_out - out_expected),
        out_expected=out_expected,
        exact=r.sqrt_price_x96 == sqrt_price_x96 and r.amount_out == out_expected,
    )


def swap_check_ok(c: SwapCheck) -> bool:
    """A1's tolerance (plan Ruling 2)."""
    out_tol = max(A1_OUT_ABS_TOL, A1_OUT_REL_TOL * abs(c.out_expected))
    return c.sqrt_rel_err < A1_SQRT_REL_TOL and c.out_abs_err <= out_tol
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_v3swap.py tests/test_integration.py -q`
Expected: PASS. If `test_v3swap_reproduces_fixture_swaps` fails, print the first failing `SwapCheck`
and compare the step targets against the word-boundary rule before touching the tolerance: the
tolerance is fixed by Ruling 2.

- [ ] **Step 5: Lint, type-check, full tests, commit, push**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/v3swap.py tests/test_v3swap.py tests/test_integration.py
git commit -m "Add exact-integer V3 swap simulation and swap-event check"
git push
```

---

### Task 4: Arbitrage to the Binance price

**Files:**
- Modify: `src/uniswap_lp_economics/v3swap.py`
- Test: `tests/test_v3swap.py`

**Interfaces:**
- Consumes: `swap_exact_input`, `v3math.sqrt_price_x96_to_eth_price`,
  `v3math.eth_price_to_sqrt_price_x96`, `config.DECIMALS0/1`.
- Produces: `ArbResult(direction: str, amount_in: int, amount_out: int, profit_usd: float)` (frozen
  dataclass; `direction` is `"buy_eth"`, `"sell_eth"` or `"none"`) and
  `arb_to_price(book, p_cex_usd: float, fee_pips: int = FEE_PIPS, cex_fee_bp: float = 0.0, tick_spacing: int = TICK_SPACING) -> ArbResult`.

- [ ] **Step 1: Write the tests**

Append to `tests/test_v3swap.py` (extend the imports with `ArbResult`, `arb_to_price`, and from
`uniswap_lp_economics.v3math` import `eth_price_to_sqrt_price_x96`, `get_tick_at_sqrt_ratio`,
`sqrt_price_x96_to_eth_price`):

```python
def arb_book(price: float = 2000.0) -> TickBook:
    sqrt = eth_price_to_sqrt_price_x96(price)
    tick = get_tick_at_sqrt_ratio(sqrt)
    b = TickBook(tick=tick, sqrt_price_x96=sqrt, liquidity=0)
    b.apply_mint((tick // 10 - 500) * 10, (tick // 10 + 500) * 10, L)
    return b


def _profit(book: TickBook, buy_eth: bool, amount_in: int, p: float, c_bp: float = 0.0) -> float:
    r = swap_exact_input(book, buy_eth, amount_in)
    c = c_bp / 1e4
    if buy_eth:
        return r.amount_out / 1e18 * p * (1 - c) - r.amount_in / 1e6
    return r.amount_out / 1e6 - r.amount_in / 1e18 * p * (1 + c)


def test_arb_on_cheap_pool_buys_eth_up_to_fee_adjusted_price() -> None:
    b = arb_book(2000.0)
    r = arb_to_price(b, 2010.0)
    assert r.direction == "buy_eth" and r.profit_usd > 0
    end = swap_exact_input(b, True, r.amount_in)
    assert sqrt_price_x96_to_eth_price(end.sqrt_price_x96) == pytest.approx(
        2010.0 * (1 - 0.0005), rel=1e-9
    )


def test_arb_on_expensive_pool_sells_eth_down_to_fee_adjusted_price() -> None:
    b = arb_book(2000.0)
    r = arb_to_price(b, 1990.0)
    assert r.direction == "sell_eth" and r.profit_usd > 0
    end = swap_exact_input(b, False, r.amount_in)
    assert sqrt_price_x96_to_eth_price(end.sqrt_price_x96) == pytest.approx(
        1990.0 / (1 - 0.0005), rel=1e-9
    )


def test_arb_amount_maximises_profit() -> None:
    b = arb_book(2000.0)
    for p, buy in ((2010.0, True), (1990.0, False)):
        r = arb_to_price(b, p)
        assert _profit(b, buy, r.amount_in, p) == pytest.approx(r.profit_usd, rel=1e-9)
        assert _profit(b, buy, int(r.amount_in * 0.9), p) < r.profit_usd
        assert _profit(b, buy, int(r.amount_in * 1.1), p) < r.profit_usd


def test_no_arb_inside_fee_band() -> None:
    assert arb_to_price(arb_book(2000.0), 2000.5) == ArbResult("none", 0, 0, 0.0)


def test_cex_fee_reduces_profit() -> None:
    b = arb_book(2000.0)
    with_fee = arb_to_price(b, 2010.0, cex_fee_bp=1.0).profit_usd
    assert 0 < with_fee < arb_to_price(b, 2010.0).profit_usd
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_v3swap.py -q`
Expected: FAIL (`ArbResult` / `arb_to_price` not defined).

- [ ] **Step 3: Implement**

Append to `src/uniswap_lp_economics/v3swap.py` (and extend its imports with `DECIMALS0`,
`DECIMALS1` from config and `eth_price_to_sqrt_price_x96`, `sqrt_price_x96_to_eth_price` from
v3math):

```python
_HUGE = 2**128  # more than the pool could ever pay out; the price limit stops the swap


@dataclass(frozen=True)
class ArbResult:
    direction: str  # "buy_eth" (USDC in), "sell_eth" (WETH in) or "none"
    amount_in: int
    amount_out: int
    profit_usd: float


_NO_ARB = ArbResult("none", 0, 0, 0.0)


def arb_to_price(
    book: TickBook,
    p_cex_usd: float,
    fee_pips: int = FEE_PIPS,
    cex_fee_bp: float = 0.0,
    tick_spacing: int = TICK_SPACING,
) -> ArbResult:
    """Arbitrage the pool against a CEX price, before gas (spec 6.5, plan Ruling 1).

    The arbitrageur trades until the pool's marginal price after the swap fee equals the CEX price
    after the CEX fee: buying ETH from a cheap pool stops at P_cex*(1-f)*(1-c); selling ETH into an
    expensive pool stops at P_cex*(1+c)/(1-f). Profit is valued at the CEX price after its fee.
    """
    f = fee_pips / _PIPS
    c = cex_fee_bp / 10_000
    pool = sqrt_price_x96_to_eth_price(book.sqrt_price_x96)
    low = p_cex_usd * (1 - f) * (1 - c)
    high = p_cex_usd * (1 + c) / (1 - f)
    if pool < low:  # ETH cheap in the pool: pay USDC, receive ETH, sell it on the CEX
        limit = eth_price_to_sqrt_price_x96(low)
        if limit >= book.sqrt_price_x96:  # float rounding at the band edge
            return _NO_ARB
        r = swap_exact_input(book, True, _HUGE, limit, fee_pips, tick_spacing)
        profit = r.amount_out / 10**DECIMALS1 * p_cex_usd * (1 - c) - r.amount_in / 10**DECIMALS0
        return ArbResult("buy_eth", r.amount_in, r.amount_out, profit)
    if pool > high:  # ETH expensive in the pool: pay WETH, receive USDC, buy ETH back on the CEX
        limit = eth_price_to_sqrt_price_x96(high)
        if limit <= book.sqrt_price_x96:
            return _NO_ARB
        r = swap_exact_input(book, False, _HUGE, limit, fee_pips, tick_spacing)
        profit = r.amount_out / 10**DECIMALS0 - r.amount_in / 10**DECIMALS1 * p_cex_usd * (1 + c)
        return ArbResult("sell_eth", r.amount_in, r.amount_out, profit)
    return _NO_ARB
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_v3swap.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, full tests, commit, push**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/v3swap.py tests/test_v3swap.py
git commit -m "Add arbitrage-to-price: optimal trade against a CEX price, before gas"
git push
```

---

### Task 5: Curated labels and flow labelling (`flows.py`)

**Files:**
- Create: `labels/addresses.csv`, `src/uniswap_lp_economics/flows.py`, `tests/test_flows.py`
- Modify: `src/uniswap_lp_economics/config.py`

**Interfaces:**
- Produces:
  - `config.LABELS_CSV = ROOT / "labels" / "addresses.csv"`
  - `flows.CATEGORIES = ("uniswap_router", "aggregator", "intent_settlement")`,
    `flows.FLOW_LABELS = (*CATEGORIES, "searcher", "other_contract")`,
    `flows.SIZE_BUCKETS = ("<1k", "1k-10k", "10k-100k", ">=100k")`
  - `flows.load_labels(path: Path) -> pl.DataFrame` (columns `address, name, category, source_url, notes`)
  - `flows.size_bucket(notional: pl.Expr) -> pl.Expr`
  - `flows.label_swaps(swaps: pl.DataFrame, labels: pl.DataFrame) -> pl.DataFrame` adds
    `flow_label` (str), `top_of_block` (bool), `size_bucket` (str); needs `to_address`, `sender`,
    `transaction_index`, `notional_usd`
  - `flows.top_bots(labelled: pl.DataFrame, coverage: float = 0.9, cap: int = 25) -> list[str]`
  - `flows.label_coverage(labelled) -> pl.DataFrame` (`flow_label, swaps, notional_usd, notional_share`)
  - `flows.top_unlabelled(labelled, column: str, n: int = 30) -> pl.DataFrame` (`address, swaps, notional_usd`)

- [ ] **Step 1: Write the tests**

Create `tests/test_flows.py`:

```python
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics import config
from uniswap_lp_economics.flows import (
    label_coverage,
    label_swaps,
    load_labels,
    top_bots,
    top_unlabelled,
)

ROUTER = "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45"
COW = "0x9008d19f58aabd9ed0d60971565aa8510560ab41"
BOT = "0x" + "b0" * 20
CONTRACT = "0x" + "c1" * 20
OTHER = "0x" + "d2" * 20
HEADER = "address,name,category,source_url,notes\n"
GOOD = HEADER + (
    f"{ROUTER},Uniswap SwapRouter02,uniswap_router,https://example.org/a,\n"
    f"{COW},CoW GPv2Settlement,intent_settlement,https://example.org/b,batch auctions\n"
)


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "labels.csv"
    p.write_text(text)
    return p


def swaps(rows: list[tuple[str | None, str, int, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "to_address": pl.String,
            "sender": pl.String,
            "transaction_index": pl.Int64,
            "notional_usd": pl.Float64,
        },
        orient="row",
    )


def test_label_rules_first_match_wins(tmp_path: Path) -> None:
    labels = load_labels(write(tmp_path, GOOD))
    out = label_swaps(
        swaps(
            [
                (ROUTER, ROUTER, 0, 500.0),  # tx target in list
                (COW, BOT, 1, 5_000.0),  # tx target beats a non-listed pool caller
                (OTHER, ROUTER, 2, 50_000.0),  # pool caller in list
                (BOT, BOT, 3, 500_000.0),  # contract called directly: searcher
                (OTHER, CONTRACT, 9, 999.99),
                (None, CONTRACT, 9, 1_000.0),  # contract creation tx
            ]
        ),
        labels,
    )
    assert out["flow_label"].to_list() == [
        "uniswap_router",
        "intent_settlement",
        "uniswap_router",
        "searcher",
        "other_contract",
        "other_contract",
    ]
    assert out["top_of_block"].to_list() == [True, True, True, False, False, False]
    assert out["size_bucket"].to_list() == ["<1k", "1k-10k", "10k-100k", ">=100k", "<1k", "1k-10k"]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (HEADER + f"{ROUTER.upper()},X,uniswap_router,https://e.org,\n", "line 2: address"),
        (HEADER + f"{ROUTER},X,dex,https://e.org,\n", "line 2: category"),
        (HEADER + f"{ROUTER},X,uniswap_router,,\n", "line 2: source_url"),
        (HEADER + f"{ROUTER},,uniswap_router,https://e.org,\n", "line 2: name"),
        (GOOD + f"{ROUTER},Again,uniswap_router,https://e.org,\n", "duplicate"),
        ("address,name,category\n", "columns"),
    ],
)
def test_load_labels_rejects_bad_rows(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        load_labels(write(tmp_path, text))


def test_top_bots_coverage_and_cap() -> None:
    a, b, c = "0x" + "0a" * 20, "0x" + "0b" * 20, "0x" + "0c" * 20
    labelled = swaps([(a, a, 0, 60.0), (b, b, 0, 30.0), (c, c, 0, 10.0), (OTHER, a, 0, 99.0)])
    labelled = labelled.with_columns(
        flow_label=pl.Series(["searcher", "searcher", "searcher", "other_contract"])
    )
    assert top_bots(labelled) == [a, b]
    assert top_bots(labelled, coverage=0.95) == [a, b, c]
    assert top_bots(labelled, cap=1) == [a]
    assert top_bots(labelled.filter(pl.col("flow_label") != "searcher")) == []


def test_coverage_tables(tmp_path: Path) -> None:
    labels = load_labels(write(tmp_path, GOOD))
    labelled = label_swaps(swaps([(ROUTER, ROUTER, 0, 100.0), (OTHER, CONTRACT, 0, 300.0)]), labels)
    cov = label_coverage(labelled)
    assert dict(zip(cov["flow_label"], cov["notional_share"], strict=True)) == {
        "uniswap_router": 0.25,
        "other_contract": 0.75,
    }
    assert top_unlabelled(labelled, "sender")["address"].to_list() == [CONTRACT]


def test_repo_labels_file_is_valid() -> None:
    labels = load_labels(config.LABELS_CSV)
    assert labels.height >= 10
    assert ROUTER in labels["address"].to_list()
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_flows.py -q`
Expected: FAIL (no module `flows`).

- [ ] **Step 3: Implement `flows.py` and the config constant**

Add to `src/uniswap_lp_economics/config.py` (after `VALIDATION_DIR`):

```python
LABELS_CSV = ROOT / "labels" / "addresses.csv"
```

Create `src/uniswap_lp_economics/flows.py`:

```python
"""Flow labels for swaps: a curated address list first, then structural heuristics (spec 5.4)."""

import re
from pathlib import Path

import polars as pl

CATEGORIES = ("uniswap_router", "aggregator", "intent_settlement")
FLOW_LABELS = (*CATEGORIES, "searcher", "other_contract")
LABEL_COLUMNS = ["address", "name", "category", "source_url", "notes"]
SIZE_BUCKETS = ("<1k", "1k-10k", "10k-100k", ">=100k")
TOP_OF_BLOCK_MAX_INDEX = 2
TOP_BOT_COVERAGE = 0.9
TOP_BOT_CAP = 25
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


def load_labels(path: Path) -> pl.DataFrame:
    """Read and validate the curated address list; a ValueError names the offending line."""
    df = pl.read_csv(path, infer_schema=False)
    if df.columns != LABEL_COLUMNS:
        raise ValueError(f"{path}: columns must be {LABEL_COLUMNS}, got {df.columns}")
    for line, row in enumerate(df.iter_rows(named=True), start=2):  # line 1 is the header
        if not _ADDRESS.match(row["address"] or ""):
            raise ValueError(
                f"{path} line {line}: address {row['address']!r} must be 0x + 40 lowercase hex"
            )
        if row["category"] not in CATEGORIES:
            raise ValueError(f"{path} line {line}: category {row['category']!r} not in {CATEGORIES}")
        if not row["name"]:
            raise ValueError(f"{path} line {line}: name is empty")
        if not (row["source_url"] or "").startswith("https://"):
            raise ValueError(f"{path} line {line}: source_url must be an https:// link")
    dupes = sorted(set(df.filter(pl.col("address").is_duplicated())["address"].to_list()))
    if dupes:
        raise ValueError(f"{path}: duplicate addresses {dupes}")
    return df


def size_bucket(notional: pl.Expr) -> pl.Expr:
    return (
        pl.when(notional < 1_000)
        .then(pl.lit(SIZE_BUCKETS[0]))
        .when(notional < 10_000)
        .then(pl.lit(SIZE_BUCKETS[1]))
        .when(notional < 100_000)
        .then(pl.lit(SIZE_BUCKETS[2]))
        .otherwise(pl.lit(SIZE_BUCKETS[3]))
    )


def label_swaps(swaps: pl.DataFrame, labels: pl.DataFrame) -> pl.DataFrame:
    """Add flow_label, top_of_block and size_bucket. First matching rule wins: tx target listed →
    its category; pool caller listed → its category; caller == tx target → searcher; else
    other_contract."""
    cats = labels.select("address", "category")
    joined = swaps.join(
        cats.rename({"address": "to_address", "category": "_cat_to"}),
        on="to_address",
        how="left",
        maintain_order="left",
    ).join(
        cats.rename({"address": "sender", "category": "_cat_sender"}),
        on="sender",
        how="left",
        maintain_order="left",
    )
    searcher = pl.when(pl.col("sender") == pl.col("to_address")).then(pl.lit("searcher"))
    return joined.with_columns(
        flow_label=pl.coalesce("_cat_to", "_cat_sender", searcher, pl.lit("other_contract")),
        top_of_block=pl.col("transaction_index") <= TOP_OF_BLOCK_MAX_INDEX,
        size_bucket=size_bucket(pl.col("notional_usd")),
    ).drop("_cat_to", "_cat_sender")


def top_bots(
    labelled: pl.DataFrame, coverage: float = TOP_BOT_COVERAGE, cap: int = TOP_BOT_CAP
) -> list[str]:
    """Smallest set of searcher senders, ranked by notional, covering `coverage` (at most `cap`)."""
    ranked = (
        labelled.filter(pl.col("flow_label") == "searcher")
        .group_by("sender")
        .agg(pl.col("notional_usd").sum())
        .sort(["notional_usd", "sender"], descending=[True, False])
    )
    total = float(ranked["notional_usd"].sum())
    bots: list[str] = []
    covered = 0.0
    for sender, notional in ranked.iter_rows():
        if total <= 0 or covered >= coverage * total or len(bots) == cap:
            break
        bots.append(sender)
        covered += notional
    return bots


def label_coverage(labelled: pl.DataFrame) -> pl.DataFrame:
    total = float(labelled["notional_usd"].sum())
    share = pl.col("notional_usd") / total if total > 0 else pl.lit(None, dtype=pl.Float64)
    return (
        labelled.group_by("flow_label")
        .agg(swaps=pl.len(), notional_usd=pl.col("notional_usd").sum())
        .with_columns(notional_share=share)
        .sort("notional_usd", descending=True)
    )


def top_unlabelled(labelled: pl.DataFrame, column: str, n: int = 30) -> pl.DataFrame:
    """The `column` values (sender or to_address) of other_contract swaps with most notional."""
    return (
        labelled.filter(pl.col("flow_label") == "other_contract")
        .group_by(pl.col(column).alias("address"))
        .agg(swaps=pl.len(), notional_usd=pl.col("notional_usd").sum())
        .sort(["notional_usd", "address"], descending=[True, False])
        .head(n)
    )
```

- [ ] **Step 4: Build `labels/addresses.csv` from verified sources**

Create `labels/addresses.csv` with the header `address,name,category,source_url,notes`. Candidates are
listed below. **Verify every address before adding it.** Use WebFetch on the project's official
deployment page, or on `https://etherscan.io/address/<address>` and confirm the public name tag.
Put the page you confirmed it on in `source_url`. Addresses go in lowercase. Leave out any candidate you
cannot confirm. You may add further public routers, aggregators or settlement contracts from the same
official pages. Aim for at least 10 verified rows.

| Candidate address | Expected name | Category |
|---|---|---|
| `0xe592427a0aece92de3edee1f18e0157c05861564` | Uniswap V3 SwapRouter | uniswap_router |
| `0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45` | Uniswap SwapRouter02 | uniswap_router |
| `0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b` | Uniswap Universal Router (v1) | uniswap_router |
| `0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad` | Uniswap Universal Router (v1.2) | uniswap_router |
| `0x66a9893cc07d91d95644aedd05d03f95e1dba8af` | Uniswap Universal Router (v2, v4) | uniswap_router |
| `0x6000da47483062a0d734ba3dc7576ce6a0b645c4` | UniswapX ExclusiveDutchOrderReactor | intent_settlement |
| `0x00000011f84b9aa48e5f8aa8b9897600006289be` | UniswapX V2DutchOrderReactor | intent_settlement |
| `0x9008d19f58aabd9ed0d60971565aa8510560ab41` | CoW Protocol GPv2Settlement | intent_settlement |
| `0x1111111254eeb25477b68fb85ed929f73a960582` | 1inch AggregationRouterV5 | aggregator |
| `0x111111125421ca6dc452d289314280a0f8842a65` | 1inch AggregationRouterV6 | aggregator |
| `0xdef1c0ded9bec7f1a1670819833240f027b25eff` | 0x Exchange Proxy | aggregator |
| `0xdef171fe48cf0115b1d80b88dc8eab59176fee57` | ParaSwap Augustus V5 | aggregator |
| `0x6a000f20005980200259b80c5102003040001068` | ParaSwap / Velora Augustus V6.2 | aggregator |
| `0x6131b5fae19ea4f9d964eac0408e4408b66337b5` | KyberSwap MetaAggregationRouterV2 | aggregator |
| `0xcf5540fffcdc3d510b18bfca6d2b9987b0772559` | Odos Router V2 | aggregator |
| `0x881d40237659c251811cec9c364ef91dc08d300c` | MetaMask Swap Router | aggregator |

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_flows.py -q`
Expected: PASS (including `test_repo_labels_file_is_valid`).

- [ ] **Step 6: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add labels/addresses.csv src/uniswap_lp_economics/flows.py src/uniswap_lp_economics/config.py tests/test_flows.py
git commit -m "Add curated address labels and swap flow labelling"
git push
```

---

### Task 6: BigQuery fetches for blocks and bot transactions (`data/blocks.py`)

**Files:**
- Create: `src/uniswap_lp_economics/data/blocks.py`, `tests/test_blocks.py`
- Modify: `src/uniswap_lp_economics/config.py`

**Interfaces:**
- Consumes: `data.bigquery.DATASET`, `data.bigquery.MAX_GB_BILLED`, `config.GCP_PROJECT`,
  `config.POOL_ADDRESS`.
- Produces:
  - `config.USDC_ADDRESS`, `config.WETH_ADDRESS` (lowercase strings)
  - `blocks.BLOCKS_FILE = "blocks.parquet"`, `blocks.OTHER_LOGS_FILE = "bot_tx_other_logs.parquet"`
  - `build_blocks_query(start: date, end: date) -> str`
  - `build_other_logs_query(start: date, end: date, bots: list[str]) -> str`
  - `fetch_blocks(raw_dir: Path, start: date, end: date, dry_run: bool = False) -> Path | None` →
    `raw_dir/blocks.parquet` (`block_number` Int64, `block_timestamp` Datetime(us, UTC), `miner` str,
    `base_fee_per_gas` Int64)
  - `fetch_bot_tx_logs(raw_dir, start, end, bots, dry_run=False) -> Path | None` →
    `raw_dir/bot_tx_other_logs.parquet` (`tx_hash`, `bot`, `other_logs` Int64, `logs` Int64) plus
    `raw_dir/bot_tx_other_logs.json` (`{"bots": [...]}`, written last)
  - `bot_tx_logs_current(raw_dir: Path, bots: list[str]) -> bool`

- [ ] **Step 1: Write the tests**

Create `tests/test_blocks.py`:

```python
import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics.config import POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS
from uniswap_lp_economics.data.blocks import (
    bot_tx_logs_current,
    build_blocks_query,
    build_other_logs_query,
)

BOT1, BOT2, BOT3 = ("0x" + c * 40 for c in "123")
START, END = date(2026, 7, 1), date(2026, 10, 1)


def test_blocks_query_filters_partition_and_selects_fields() -> None:
    q = build_blocks_query(START, END)
    assert "timestamp >= TIMESTAMP('2026-07-01')" in q
    assert "timestamp < TIMESTAMP('2026-10-01')" in q
    for col in ("number", "miner", "base_fee_per_gas"):
        assert col in q


def test_other_logs_query_lists_bots_and_allowed_addresses() -> None:
    q = build_other_logs_query(START, END, [BOT1, BOT2])
    # Partition filters on both the transactions and the logs table.
    assert q.count("block_timestamp >= TIMESTAMP('2026-07-01')") == 2
    assert q.count("block_timestamp < TIMESTAMP('2026-10-01')") == 2
    assert f"'{BOT1}'" in q and f"'{BOT2}'" in q
    for addr in (POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS):
        assert f"'{addr}'" in q


@pytest.mark.parametrize("bots", [[], ["0xABC' OR 1=1 --"], [BOT1.upper()]])
def test_other_logs_query_rejects_bad_bot_lists(bots: list[str]) -> None:
    with pytest.raises(ValueError):
        build_other_logs_query(START, END, bots)


def test_bot_tx_logs_current(tmp_path: Path) -> None:
    assert not bot_tx_logs_current(tmp_path, [BOT1])
    pl.DataFrame({"tx_hash": ["0x1"], "bot": [BOT1], "other_logs": [0], "logs": [3]}).write_parquet(
        tmp_path / "bot_tx_other_logs.parquet"
    )
    (tmp_path / "bot_tx_other_logs.json").write_text(json.dumps({"bots": [BOT1, BOT2]}))
    assert bot_tx_logs_current(tmp_path, [BOT1])
    assert bot_tx_logs_current(tmp_path, [BOT2, BOT1])
    assert not bot_tx_logs_current(tmp_path, [BOT1, BOT3])


@pytest.mark.live
def test_live_blocks_dry_run(tmp_path: Path) -> None:
    from uniswap_lp_economics.data.blocks import fetch_blocks

    assert fetch_blocks(tmp_path, date(2026, 9, 1), date(2026, 9, 2), dry_run=True) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_blocks.py -q`
Expected: FAIL (no module `data.blocks`).

- [ ] **Step 3: Implement**

Add to `src/uniswap_lp_economics/config.py` (after `DECIMALS1`):

```python
USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH_ADDRESS = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
```

Create `src/uniswap_lp_economics/data/blocks.py`:

```python
"""BigQuery fetches for sub-project 2: block metadata, and the logs inside top-bot transactions."""

import json
import re
from datetime import date
from pathlib import Path

import polars as pl
from google.cloud import bigquery

from uniswap_lp_economics.config import GCP_PROJECT, POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS
from uniswap_lp_economics.data.bigquery import DATASET, MAX_GB_BILLED

_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
BLOCKS_FILE = "blocks.parquet"
OTHER_LOGS_FILE = "bot_tx_other_logs.parquet"
OTHER_LOGS_META = "bot_tx_other_logs.json"


def _window(column: str, start: date, end: date) -> str:
    return (
        f"{column} >= TIMESTAMP('{start.isoformat()}') "
        f"AND {column} < TIMESTAMP('{end.isoformat()}')"
    )


def build_blocks_query(start: date, end: date) -> str:
    return f"""
SELECT number AS block_number, timestamp AS block_timestamp, miner, base_fee_per_gas
FROM `{DATASET}.blocks`
WHERE {_window("timestamp", start, end)}
ORDER BY number
"""


def build_other_logs_query(start: date, end: date, bots: list[str]) -> str:
    """Per transaction sent to a top bot: logs emitted by anything other than our pool, USDC,
    WETH or the bot itself (non-zero means the transaction also traded elsewhere)."""
    if not bots:
        raise ValueError("no bot addresses given")
    for b in bots:
        if not _ADDRESS.match(b):
            raise ValueError(f"bot address {b!r} must be 0x + 40 lowercase hex")
    listed = ", ".join(f"'{b}'" for b in bots)
    allowed = ", ".join(f"'{a}'" for a in (POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS))
    return f"""
WITH bot_txs AS (
  SELECT `hash` AS tx_hash, to_address
  FROM `{DATASET}.transactions`
  WHERE {_window("block_timestamp", start, end)} AND to_address IN ({listed})
)
SELECT b.tx_hash, b.to_address AS bot,
       COUNTIF(l.address NOT IN ({allowed}) AND l.address != b.to_address) AS other_logs,
       COUNT(*) AS logs
FROM bot_txs b
JOIN `{DATASET}.logs` l ON l.transaction_hash = b.tx_hash
WHERE {_window("l.block_timestamp", start, end)}
GROUP BY b.tx_hash, b.to_address
"""


def _run(query: str, dry_run: bool) -> pl.DataFrame | None:
    client = bigquery.Client(project=GCP_PROJECT)
    dry = client.query(query, job_config=bigquery.QueryJobConfig(dry_run=True))
    print(f"  scans {(dry.total_bytes_processed or 0) / 1e9:.1f} GB")
    if dry_run:
        return None
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=int(MAX_GB_BILLED * 1e9))
    df = pl.from_arrow(client.query(query, job_config=job_config).result().to_arrow())
    assert isinstance(df, pl.DataFrame)
    return df


def _write(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    df.write_parquet(part)
    part.replace(path)


def fetch_blocks(raw_dir: Path, start: date, end: date, dry_run: bool = False) -> Path | None:
    print(f"blocks {start} -> {end}:")
    df = _run(build_blocks_query(start, end), dry_run)
    if df is None:
        return None
    df = df.with_columns(
        pl.col("block_number").cast(pl.Int64), pl.col("base_fee_per_gas").cast(pl.Int64)
    )
    out = raw_dir / BLOCKS_FILE
    _write(df, out)
    print(f"  wrote {df.height:,} blocks to {out}")
    return out


def fetch_bot_tx_logs(
    raw_dir: Path, start: date, end: date, bots: list[str], dry_run: bool = False
) -> Path | None:
    print(f"other logs in transactions to {len(bots)} top bots, {start} -> {end}:")
    df = _run(build_other_logs_query(start, end, bots), dry_run)
    if df is None:
        return None
    df = df.with_columns(pl.col("other_logs").cast(pl.Int64), pl.col("logs").cast(pl.Int64))
    out = raw_dir / OTHER_LOGS_FILE
    _write(df, out)
    # The bot list is the freshness marker, so it is written last.
    meta = raw_dir / OTHER_LOGS_META
    part = meta.with_name(meta.name + ".part")
    part.write_text(json.dumps({"bots": sorted(bots)}, indent=2))
    part.replace(meta)
    print(f"  wrote {df.height:,} transactions to {out}")
    return out


def bot_tx_logs_current(raw_dir: Path, bots: list[str]) -> bool:
    """True when the other-log data on disk was fetched for (at least) these bots."""
    meta = raw_dir / OTHER_LOGS_META
    if not meta.exists() or not (raw_dir / OTHER_LOGS_FILE).exists():
        return False
    fetched = set(json.loads(meta.read_text())["bots"])
    return set(bots) <= fetched
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_blocks.py -q`
Expected: PASS (the live test is skipped).

- [ ] **Step 5: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/data/blocks.py src/uniswap_lp_economics/config.py tests/test_blocks.py
git commit -m "Add BigQuery fetches for block metadata and top-bot transaction logs"
git push
```

---

### Task 7: Alchemy builder-payment transfers and the two fetch commands

**Files:**
- Create: `src/uniswap_lp_economics/data/transfers.py`, `tests/test_transfers.py`
- Modify: `src/uniswap_lp_economics/cli.py`

**Interfaces:**
- Consumes: `rpc.RpcClient.request`, `io.write_exact` / `io.read_exact`, `flows.load_labels`,
  `flows.label_swaps`, `flows.top_bots`, `data.blocks.fetch_blocks`, `data.blocks.fetch_bot_tx_logs`,
  `data.blocks.bot_tx_logs_current`, `data.blocks.BLOCKS_FILE`.
- Produces:
  - `transfers.TRANSFER_SCHEMA` (`block_number` Int64, `tx_hash` str, `from_address` str,
    `to_address` str, `value_wei` Int128)
  - `transfers.fetch_internal_transfers(client: RpcClient, address: str, from_block: int, to_block: int) -> pl.DataFrame`
  - `transfers.fetch_bot_transfers(client, raw_dir: Path, bots: list[str], from_block: int, to_block: int) -> None`
    (cache: `raw_dir/bot_transfers/<address>.parquet`)
  - `transfers.load_bot_transfers(raw_dir: Path, bots: list[str]) -> pl.DataFrame`
  - CLI `ulpe fetch-blocks [--dry-run]`, `ulpe fetch-transfers`; `cli.labelled_swaps() -> pl.DataFrame`

- [ ] **Step 1: Write the tests**

Create `tests/test_transfers.py`:

```python
import json
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest

from uniswap_lp_economics.data.transfers import (
    fetch_bot_transfers,
    fetch_internal_transfers,
    load_bot_transfers,
)
from uniswap_lp_economics.rpc import RpcClient

URL = "https://example.invalid/v2/SECRETKEY"
BOT = "0x" + "b0" * 20
BOT2 = "0x" + "b1" * 20
MINER = "0x" + "ee" * 20


def transfer(block: int, tx: str, frm: str, to: str, wei: int) -> dict[str, Any]:
    return {
        "blockNum": hex(block),
        "hash": tx,
        "from": frm,
        "to": to,
        "value": wei / 1e18,
        "rawContract": {"value": hex(wei), "address": None, "decimal": "0x12"},
        "category": "internal",
        "uniqueId": f"{tx}:internal:0",
    }


def fake(pages: list[dict[str, Any]]) -> tuple[RpcClient, list[dict[str, Any]]]:
    """A client whose n-th request gets pages[n]; the request params are recorded."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["params"][0])
        result = pages[len(seen) - 1]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    return RpcClient(URL, transport=httpx.MockTransport(handler), backoff_s=0), seen


def test_fetch_internal_transfers_follows_page_keys() -> None:
    client, seen = fake(
        [
            {"transfers": [transfer(10, "0xAA", BOT.upper(), MINER, 5)], "pageKey": "k1"},
            {"transfers": [transfer(11, "0xbb", BOT, MINER, 2**70)]},
        ]
    )
    df = fetch_internal_transfers(client, BOT, 1, 20)
    assert df["value_wei"].to_list() == [5, 2**70]
    assert df["tx_hash"].to_list() == ["0xaa", "0xbb"]
    assert df["from_address"].to_list() == [BOT, BOT]
    assert df["block_number"].to_list() == [10, 11]
    assert seen[0]["category"] == ["internal"]
    assert seen[0]["fromAddress"] == BOT and seen[0]["fromBlock"] == hex(1)
    assert seen[0]["toBlock"] == hex(20)
    assert "pageKey" not in seen[0] and seen[1]["pageKey"] == "k1"


def test_fetch_bot_transfers_caches_per_contract(tmp_path: Path) -> None:
    client, seen = fake([{"transfers": [transfer(10, "0x01", BOT, MINER, 7)]}, {"transfers": []}])
    fetch_bot_transfers(client, tmp_path, [BOT, BOT2], 1, 20)
    assert len(seen) == 2
    fetch_bot_transfers(client, tmp_path, [BOT, BOT2], 1, 20)  # all cached: no requests
    assert len(seen) == 2
    df = load_bot_transfers(tmp_path, [BOT, BOT2])
    assert df["value_wei"].to_list() == [7]
    assert df.schema["value_wei"] == pl.Int128


def test_load_bot_transfers_names_missing_bots(tmp_path: Path) -> None:
    client, _ = fake([{"transfers": []}])
    fetch_bot_transfers(client, tmp_path, [BOT], 1, 20)
    with pytest.raises(FileNotFoundError, match="ulpe fetch-transfers"):
        load_bot_transfers(tmp_path, [BOT, BOT2])


@pytest.mark.live
def test_live_internal_transfers_from_weth() -> None:
    from uniswap_lp_economics import config

    assert config.ETH_RPC_URL
    client = RpcClient(config.ETH_RPC_URL)
    df = fetch_internal_transfers(client, config.WETH_ADDRESS, 25_433_939, 25_433_941)
    assert set(df.columns) == {"block_number", "tx_hash", "from_address", "to_address", "value_wei"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_transfers.py -q`
Expected: FAIL (no module `data.transfers`).

- [ ] **Step 3: Implement `data/transfers.py`**

Create `src/uniswap_lp_economics/data/transfers.py`:

```python
"""Internal ETH transfers sent by the top bot contracts, via Alchemy's alchemy_getAssetTransfers.

A direct builder payment (block.coinbase.transfer) shows up as an internal transfer from the bot
contract to the block's fee recipient; arbprofit.py does that matching.
"""

from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.io import read_exact, write_exact
from uniswap_lp_economics.rpc import RpcClient

TRANSFER_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "tx_hash": pl.String,
    "from_address": pl.String,
    "to_address": pl.String,
    "value_wei": pl.Int128,
}
PAGE_SIZE = 1000
TRANSFERS_DIR = "bot_transfers"


def fetch_internal_transfers(
    client: RpcClient, address: str, from_block: int, to_block: int
) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    page_key: str | None = None
    while True:
        params: dict[str, Any] = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "fromAddress": address,
            "category": ["internal"],
            "excludeZeroValue": True,
            "withMetadata": False,
            "maxCount": hex(PAGE_SIZE),
        }
        if page_key:
            params["pageKey"] = page_key
        result = client.request("alchemy_getAssetTransfers", [params])
        for t in result["transfers"]:
            raw_value = (t.get("rawContract") or {}).get("value")
            if raw_value is None:
                raise ValueError(f"transfer {t.get('uniqueId')} has no rawContract.value")
            rows.append(
                {
                    "block_number": int(t["blockNum"], 16),
                    "tx_hash": t["hash"].lower(),
                    "from_address": t["from"].lower(),
                    "to_address": (t["to"] or "").lower(),
                    "value_wei": int(raw_value, 16),
                }
            )
        page_key = result.get("pageKey")
        if not page_key:
            return pl.DataFrame(rows, schema=TRANSFER_SCHEMA)


def fetch_bot_transfers(
    client: RpcClient, raw_dir: Path, bots: list[str], from_block: int, to_block: int
) -> None:
    """Fetch each bot's transfers once; a contract whose file exists is skipped."""
    out_dir = raw_dir / TRANSFERS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, bot in enumerate(bots, start=1):
        out = out_dir / f"{bot}.parquet"
        if out.exists():
            print(f"  {i}/{len(bots)} {bot}: cached")
            continue
        df = fetch_internal_transfers(client, bot, from_block, to_block)
        write_exact(df, out)
        print(f"  {i}/{len(bots)} {bot}: {df.height:,} transfers")


def load_bot_transfers(raw_dir: Path, bots: list[str]) -> pl.DataFrame:
    """Transfers for exactly these bots; FileNotFoundError if any bot was never fetched."""
    out_dir = raw_dir / TRANSFERS_DIR
    missing = [b for b in bots if not (out_dir / f"{b}.parquet").exists()]
    if missing:
        raise FileNotFoundError(
            f"no transfer data for {len(missing)} top bot(s), e.g. {missing[0]}; "
            "run `ulpe fetch-transfers`"
        )
    frames = [read_exact(out_dir / f"{b}.parquet") for b in bots]
    if not frames:
        return pl.DataFrame(schema=TRANSFER_SCHEMA)
    return pl.concat(frames)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_transfers.py -q`
Expected: PASS (the live test is skipped).

- [ ] **Step 5: Add the two CLI commands**

In `src/uniswap_lp_economics/cli.py`:
- change the imports to
  `from uniswap_lp_economics import build, config, flows, snapshot, validate`,
  `from uniswap_lp_economics.data import bigquery, binance, transfers`,
  `from uniswap_lp_economics.data import blocks as bq_blocks`,
  `from uniswap_lp_economics.io import read_exact, write_exact, write_text_atomic`;
- add these functions above `main()`:

```python
def labelled_swaps() -> pl.DataFrame:
    path = config.INTERIM_DIR / "swaps.parquet"
    if not path.exists():
        raise SystemExit(f"{path} missing; run `ulpe build` first")
    return flows.label_swaps(read_exact(path), flows.load_labels(config.LABELS_CSV))


def fetch_blocks(dry_run: bool) -> None:
    bots = flows.top_bots(labelled_swaps())
    print(f"top bots: {len(bots)}")
    if dry_run or not (config.RAW_DIR / bq_blocks.BLOCKS_FILE).exists():
        bq_blocks.fetch_blocks(config.RAW_DIR, config.WINDOW_START, config.WINDOW_END, dry_run)
    else:
        print("blocks already downloaded, skipping")
    if dry_run or not bq_blocks.bot_tx_logs_current(config.RAW_DIR, bots):
        bq_blocks.fetch_bot_tx_logs(
            config.RAW_DIR, config.WINDOW_START, config.WINDOW_END, bots, dry_run
        )
    else:
        print("top-bot transaction logs already downloaded for these bots, skipping")


def fetch_transfers() -> None:
    labelled = labelled_swaps()
    bots = flows.top_bots(labelled)
    lo = int(labelled["block_number"].min())  # type: ignore[arg-type]
    hi = int(labelled["block_number"].max())  # type: ignore[arg-type]
    print(f"internal transfers from {len(bots)} top bots, blocks {lo}-{hi}:")
    transfers.fetch_bot_transfers(_rpc(), config.RAW_DIR, bots, lo, hi)
```

- register the parsers after `fetch-cex`:

```python
    blocks_cmd = sub.add_parser(
        "fetch-blocks", help="download block miners/base fees and top-bot tx logs (BigQuery)"
    )
    blocks_cmd.add_argument("--dry-run", action="store_true", help="only report bytes scanned")
    sub.add_parser("fetch-transfers", help="download top-bot internal ETH transfers (Alchemy)")
```

- and dispatch them (before the `build` branch):

```python
    elif args.command == "fetch-blocks":
        fetch_blocks(args.dry_run)
    elif args.command == "fetch-transfers":
        fetch_transfers()
```

- [ ] **Step 6: Smoke-test the CLI**

Run: `uv run ulpe --help`
Expected: the list shows `fetch-blocks` and `fetch-transfers`.

- [ ] **Step 7: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/data/transfers.py src/uniswap_lp_economics/cli.py tests/test_transfers.py
git commit -m "Add Alchemy internal-transfer fetch and fetch-blocks/fetch-transfers commands"
git push
```

---

### Task 8: As-of reference prices (`align.py`)

**Files:**
- Create: `src/uniswap_lp_economics/align.py`, `tests/test_align.py`
- Modify: `src/uniswap_lp_economics/config.py`

**Interfaces:**
- Produces:
  - `config.HORIZONS_S = (0, 12, 60, 300, 3600)`
  - `align.US = 1_000_000`, `align.window_end_us() -> int` (2026-10-01 00:00 UTC in µs)
  - `align.reference_table(trades: pl.DataFrame) -> pl.DataFrame` (`ts_us`, `price`)
  - `align.kline_reference_table(klines: pl.DataFrame) -> pl.DataFrame` (`ts_us` = bar end, `price`)
  - `align.reference_at(times_us: pl.Series, ref: pl.DataFrame, end_us: int) -> pl.DataFrame`
    (`price`, `age_s`; same row order as `times_us`)
  - `align.add_reference_prices(df, ref, end_us, horizons=HORIZONS_S, shift_s=0.0) -> pl.DataFrame`
    adds `t0_us` (Int64) and `p_cex_{h}`, `cex_age_s_{h}` for each horizon; needs `block_timestamp`

- [ ] **Step 1: Write the tests**

Create `tests/test_align.py`:

```python
from datetime import UTC, datetime

import polars as pl

from uniswap_lp_economics.align import (
    add_reference_prices,
    kline_reference_table,
    reference_at,
    reference_table,
    window_end_us,
)

REF = pl.DataFrame({"ts_us": [1_000_000, 2_000_000, 5_000_000], "price": [100.0, 101.0, 102.0]})
END = 10_000_000


def test_reference_at_picks_last_trade_at_or_before() -> None:
    r = reference_at(pl.Series([2_000_000, 4_500_000, 999_999, 1_000_000]), REF, END)
    assert r["price"].to_list() == [101.0, 101.0, None, 100.0]
    assert r["age_s"].to_list() == [0.0, 2.5, None, 0.0]


def test_reference_null_at_or_after_data_end() -> None:
    r = reference_at(pl.Series([9_999_999, 10_000_000, 12_000_000]), REF, END)
    assert r["price"].to_list() == [102.0, None, None]
    assert r["age_s"].to_list()[1:] == [None, None]


def test_reference_table_keeps_last_trade_of_a_microsecond() -> None:
    trades = pl.DataFrame({"ts_us": [5, 5, 3], "price": [1.0, 2.0, 0.5], "qty": [1.0, 1.0, 1.0]})
    ref = reference_table(trades)
    assert ref.rows() == [(3, 0.5), (5, 2.0)]


def test_kline_reference_uses_bar_end() -> None:
    k = pl.DataFrame({"ts_us": [0, 1_000_000], "close": [10.0, 11.0]})
    ref = kline_reference_table(k)
    got = reference_at(pl.Series([999_999, 1_000_000, 2_000_000]), ref, END)["price"].to_list()
    assert got == [None, 10.0, 11.0]


def test_add_reference_prices_horizons_and_shift() -> None:
    df = pl.DataFrame(
        {"block_timestamp": [datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)]},
        schema={"block_timestamp": pl.Datetime("us", "UTC")},
    )
    out = add_reference_prices(df, REF, END, horizons=(0, 1, 4))
    assert out["t0_us"].item() == 1_000_000
    assert [out[f"p_cex_{h}"].item() for h in (0, 1, 4)] == [100.0, 101.0, 102.0]
    assert out["cex_age_s_4"].item() == 0.0
    shifted = add_reference_prices(df, REF, END, horizons=(0,), shift_s=1.0)
    assert shifted["p_cex_0"].item() == 101.0


def test_window_end() -> None:
    assert window_end_us() == int(datetime(2026, 10, 1, tzinfo=UTC).timestamp()) * 1_000_000
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_align.py -q`
Expected: FAIL (no module `align`).

- [ ] **Step 3: Implement**

Add to `src/uniswap_lp_economics/config.py` (after `WINDOW_END`):

```python
HORIZONS_S = (0, 12, 60, 300, 3600)  # markout horizons after the block timestamp
```

Create `src/uniswap_lp_economics/align.py`:

```python
"""As-of reference prices: the Binance price in force at a time, and how old it is (spec 5.1)."""

from datetime import UTC, datetime, time

import polars as pl

from uniswap_lp_economics.config import HORIZONS_S, WINDOW_END

US = 1_000_000


def window_end_us() -> int:
    """End of the study window (exclusive) in µs since the epoch; the Binance data ends there."""
    return int(datetime.combine(WINDOW_END, time(), UTC).timestamp()) * US


def reference_table(trades: pl.DataFrame) -> pl.DataFrame:
    """ETHUSDC trades as a (ts_us, price) reference; the last trade of a microsecond wins."""
    return (
        trades.select("ts_us", "price")
        .sort("ts_us", maintain_order=True)
        .unique(subset="ts_us", keep="last", maintain_order=True)
    )


def kline_reference_table(klines: pl.DataFrame) -> pl.DataFrame:
    """ETHUSDT 1s klines as a reference. A bar's close is only known when the bar ends."""
    return klines.select(ts_us=pl.col("ts_us") + US, price=pl.col("close")).sort("ts_us")


def reference_at(times_us: pl.Series, ref: pl.DataFrame, end_us: int) -> pl.DataFrame:
    """Last reference price at or before each time, and its age in seconds, in input order.

    Both are null for times before the first reference point or at/after `end_us` (the data
    ends there, so the last price would be stale, not current).
    """
    query = pl.DataFrame({"t_us": times_us.cast(pl.Int64)}).with_row_index("_i").sort("t_us")
    joined = query.join_asof(
        ref.rename({"ts_us": "ref_ts_us"}).sort("ref_ts_us"),
        left_on="t_us",
        right_on="ref_ts_us",
        strategy="backward",
    ).sort("_i")
    valid = pl.col("ref_ts_us").is_not_null() & (pl.col("t_us") < end_us)
    return joined.select(
        price=pl.when(valid).then(pl.col("price")),
        age_s=pl.when(valid).then((pl.col("t_us") - pl.col("ref_ts_us")) / US),
    )


def add_reference_prices(
    df: pl.DataFrame,
    ref: pl.DataFrame,
    end_us: int,
    horizons: tuple[int, ...] = HORIZONS_S,
    shift_s: float = 0.0,
) -> pl.DataFrame:
    """Add t0_us (block time + shift) and p_cex_{h} / cex_age_s_{h} at t0 + h for each horizon."""
    t0 = df["block_timestamp"].dt.epoch("us") + int(round(shift_s * US))
    out = df.with_columns(t0_us=t0)
    for h in horizons:
        r = reference_at(t0 + h * US, ref, end_us)
        out = out.with_columns(
            r["price"].alias(f"p_cex_{h}"), r["age_s"].alias(f"cex_age_s_{h}")
        )
    return out
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_align.py -q`
Expected: PASS.

- [ ] **Step 5: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/align.py src/uniswap_lp_economics/config.py tests/test_align.py
git commit -m "Add as-of Binance reference prices at markout horizons"
git push
```

---

### Task 9: Markouts and grouped tables (`markouts.py`)

**Files:**
- Create: `src/uniswap_lp_economics/markouts.py`, `tests/test_markouts.py`

**Interfaces:**
- Consumes: `config.HORIZONS_S`; columns `amount_usdc`, `amount_eth`, `notional_usd`, `fee_usd`,
  `fee_protocol_share`, `p_cex_{h}`, `cex_age_s_0`, `block_timestamp`, `flow_label`, `size_bucket`.
- Produces:
  - `markouts.add_markouts(df, horizons=HORIZONS_S) -> pl.DataFrame` adds `protocol_fee_usd`,
    `markout_usd_{h}`, `markout_bp_{h}`, `lp_markout_usd_{h}`
  - `markouts.day_bootstrap_ci(daily_markout: NDArray[np.float64], daily_notional: NDArray[np.float64], n_boot=1000, seed=42) -> tuple[float, float]`
  - `markouts.markout_table(aligned, group_cols: list[str], horizons=HORIZONS_S, n_boot=1000, seed=42) -> pl.DataFrame`
    with `*group_cols, horizon_s, swaps, notional_usd, markout_usd, mean_bp, median_bp, ci_lo_bp, ci_hi_bp`
  - `markouts.GROUPINGS: dict[str, list[str]]`, `markouts.markout_tables(aligned, horizons=HORIZONS_S) -> pl.DataFrame`
    (all groupings stacked, first column `grouping`)
  - `markouts.exclude_stale(aligned, max_age_s: float = 5.0) -> pl.DataFrame`

- [ ] **Step 1: Write the tests**

Create `tests/test_markouts.py`:

```python
import math
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
import pytest

from uniswap_lp_economics.markouts import (
    add_markouts,
    day_bootstrap_ci,
    exclude_stale,
    markout_table,
    markout_tables,
)

H = (0, 12)
SCHEMA: dict[str, Any] = {
    "block_timestamp": pl.Datetime("us", "UTC"),
    "amount_usdc": pl.Float64,
    "amount_eth": pl.Float64,
    "notional_usd": pl.Float64,
    "fee_usd": pl.Float64,
    "fee_protocol_share": pl.Float64,
    "p_cex_0": pl.Float64,
    "p_cex_12": pl.Float64,
    "cex_age_s_0": pl.Float64,
    "flow_label": pl.String,
    "size_bucket": pl.String,
}


def frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    base: dict[str, Any] = {
        "block_timestamp": datetime(2026, 7, 1, tzinfo=UTC),
        "amount_usdc": 0.0,
        "amount_eth": 0.0,
        "notional_usd": 0.0,
        "fee_usd": 0.0,
        "fee_protocol_share": 0.25,
        "p_cex_0": 2010.0,
        "p_cex_12": 2010.0,
        "cex_age_s_0": 0.1,
        "flow_label": "searcher",
        "size_bucket": "1k-10k",
    }
    return pl.DataFrame([{**base, **r} for r in rows], schema=SCHEMA)


def test_markout_signs_hand_worked() -> None:
    out = add_markouts(
        frame(
            [
                # trader buys 1 ETH for 2001 USDC; Binance says 2010: trader +9
                {"amount_usdc": 2001.0, "amount_eth": -1.0, "notional_usd": 2001.0},
                # trader sells 1 ETH for 1990 USDC; Binance says 2010: trader -20
                {"amount_usdc": -1990.0, "amount_eth": 1.0, "notional_usd": 1990.0},
            ]
        ),
        H,
    )
    assert out["markout_usd_0"].to_list() == pytest.approx([9.0, -20.0])
    assert out["markout_bp_0"].to_list() == pytest.approx([9 / 2001 * 1e4, -20 / 1990 * 1e4])


def test_lp_markout_is_trader_loss_minus_protocol_fee() -> None:
    out = add_markouts(
        frame([{"amount_usdc": 2001.0, "amount_eth": -1.0, "notional_usd": 2001.0, "fee_usd": 1.0}]),
        H,
    )
    assert out["protocol_fee_usd"].item() == pytest.approx(0.25)
    assert out["lp_markout_usd_0"].item() == pytest.approx(-9.25)
    total = out["markout_usd_0"] + out["lp_markout_usd_0"] + out["protocol_fee_usd"]
    assert abs(total.item()) < 1e-12


def test_zero_notional_gives_null_bp() -> None:
    out = add_markouts(frame([{"amount_eth": 0.001, "notional_usd": 0.0}]), H)
    assert out["markout_usd_0"].item() == pytest.approx(-2.01)
    assert out["markout_bp_0"].item() is None


def test_missing_reference_is_null_and_excluded_per_horizon() -> None:
    df = add_markouts(
        frame(
            [
                {"amount_usdc": -1.0, "notional_usd": 1.0},
                {"amount_usdc": -1.0, "notional_usd": 1.0, "p_cex_12": None},
            ]
        ),
        H,
    )
    assert df["markout_usd_12"].to_list()[1] is None
    t = markout_table(df, [], H)
    assert dict(zip(t["horizon_s"], t["swaps"], strict=True)) == {0: 2, 12: 1}


def test_mean_bp_is_notional_weighted() -> None:
    df = add_markouts(
        frame(
            [
                {"amount_usdc": -1.0, "notional_usd": 1000.0},  # +1 USD (+10 bp)
                {"amount_usdc": 9.0, "notional_usd": 9000.0},  # -9 USD (-10 bp)
            ]
        ),
        H,
    )
    row = markout_table(df, [], (0,)).row(0, named=True)
    assert row["mean_bp"] == pytest.approx(-8.0)
    assert row["markout_usd"] == pytest.approx(-8.0)
    assert row["notional_usd"] == pytest.approx(10_000.0)


def test_day_bootstrap_ci() -> None:
    m = np.array([1.0, 2.0, 3.0, 4.0])
    n = np.array([1000.0, 1000.0, 1000.0, 1000.0])
    lo, hi = day_bootstrap_ci(m, n)
    assert lo <= 25.0 <= hi
    assert (lo, hi) == day_bootstrap_ci(m, n)  # fixed seed
    assert all(math.isnan(x) for x in day_bootstrap_ci(np.array([]), np.array([])))


def test_markout_tables_stack_every_grouping() -> None:
    df = add_markouts(frame([{"amount_usdc": -1.0, "notional_usd": 1.0}]), H)
    t = markout_tables(df, H)
    assert t.columns[0] == "grouping"
    assert set(t["grouping"]) == {"all", "flow_label", "size_bucket", "flow_label_x_size"}


def test_exclude_stale() -> None:
    df = frame([{"cex_age_s_0": 0.5}, {"cex_age_s_0": 6.0}, {"cex_age_s_0": None}])
    assert exclude_stale(df).height == 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_markouts.py -q`
Expected: FAIL (no module `markouts`).

- [ ] **Step 3: Implement**

Create `src/uniswap_lp_economics/markouts.py`:

```python
"""Markouts against Binance (spec 5.2-5.3): per-swap columns and grouped tables.

Trader side, USD: markout(h) = -(amount_usdc + amount_eth * P_cex(t0 + h)), with pool amounts
(positive = into the pool) that already include the swap fee. Positive = the swap won.
"""

import math
from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

from uniswap_lp_economics.config import HORIZONS_S

N_BOOT = 1000
SEED = 42
STALE_S = 5.0
GROUPINGS: dict[str, list[str]] = {
    "all": [],
    "flow_label": ["flow_label"],
    "size_bucket": ["size_bucket"],
    "flow_label_x_size": ["flow_label", "size_bucket"],
}


def add_markouts(df: pl.DataFrame, horizons: tuple[int, ...] = HORIZONS_S) -> pl.DataFrame:
    out = df.with_columns(protocol_fee_usd=pl.col("fee_usd") * pl.col("fee_protocol_share"))
    out = out.with_columns(
        (-(pl.col("amount_usdc") + pl.col("amount_eth") * pl.col(f"p_cex_{h}"))).alias(
            f"markout_usd_{h}"
        )
        for h in horizons
    )
    has_notional = pl.col("notional_usd") > 0
    return out.with_columns(
        *[
            pl.when(has_notional)
            .then(pl.col(f"markout_usd_{h}") / pl.col("notional_usd") * 1e4)
            .alias(f"markout_bp_{h}")
            for h in horizons
        ],
        *[
            (-pl.col(f"markout_usd_{h}") - pl.col("protocol_fee_usd")).alias(f"lp_markout_usd_{h}")
            for h in horizons
        ],
    )


def day_bootstrap_ci(
    daily_markout: NDArray[np.float64],
    daily_notional: NDArray[np.float64],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> tuple[float, float]:
    """95% interval of sum(markout) / sum(notional) in bp, resampling whole days."""
    n_days = len(daily_markout)
    if n_days == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_days, size=(n_boot, n_days))
    num = daily_markout[idx].sum(axis=1)
    den = daily_notional[idx].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        stat = np.where(den > 0, num / den * 1e4, np.nan)
    if np.isnan(stat).all():
        return math.nan, math.nan
    lo, hi = np.nanpercentile(stat, [2.5, 97.5])
    return float(lo), float(hi)


def markout_table(
    aligned: pl.DataFrame,
    group_cols: list[str],
    horizons: tuple[int, ...] = HORIZONS_S,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> pl.DataFrame:
    """Per group and horizon: swaps, notional, total markout, notional-weighted mean bp
    (= sum markout / sum notional), median bp and a 95% day-bootstrap interval.

    Swaps without a reference at a horizon are left out of that horizon only. Days come from
    the whole table, so a group's quiet days are resampled as zero-volume days.
    """
    base = aligned.with_columns(day=pl.col("block_timestamp").dt.date())
    days = base["day"].unique().sort().to_list()
    rows: list[dict[str, Any]] = []
    for h in horizons:
        m, bp = f"markout_usd_{h}", f"markout_bp_{h}"
        valid = base.filter(pl.col(m).is_not_null())
        if valid.height == 0:
            continue
        groups: dict[tuple[Any, ...], pl.DataFrame] = (
            valid.partition_by(group_cols, as_dict=True, maintain_order=True)
            if group_cols
            else {(): valid}
        )
        for key in sorted(groups, key=lambda k: tuple(str(x) for x in k)):
            g = groups[key]
            daily = g.group_by("day").agg(pl.col(m).sum(), pl.col("notional_usd").sum())
            by_day = {d: (mk, nt) for d, mk, nt in daily.iter_rows()}
            dm = np.array([by_day.get(d, (0.0, 0.0))[0] for d in days], dtype=np.float64)
            dn = np.array([by_day.get(d, (0.0, 0.0))[1] for d in days], dtype=np.float64)
            lo, hi = day_bootstrap_ci(dm, dn, n_boot, seed)
            notional = float(g["notional_usd"].sum())
            total = float(g[m].sum())
            median = g[bp].median()
            rows.append(
                {
                    **dict(zip(group_cols, key, strict=True)),
                    "horizon_s": h,
                    "swaps": g.height,
                    "notional_usd": notional,
                    "markout_usd": total,
                    "mean_bp": total / notional * 1e4 if notional > 0 else None,
                    "median_bp": None if median is None else float(median),  # type: ignore[arg-type]
                    "ci_lo_bp": lo,
                    "ci_hi_bp": hi,
                }
            )
    schema: dict[str, Any] = {
        **dict.fromkeys(group_cols, pl.String),
        "horizon_s": pl.Int64,
        "swaps": pl.Int64,
        "notional_usd": pl.Float64,
        "markout_usd": pl.Float64,
        "mean_bp": pl.Float64,
        "median_bp": pl.Float64,
        "ci_lo_bp": pl.Float64,
        "ci_hi_bp": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


def markout_tables(aligned: pl.DataFrame, horizons: tuple[int, ...] = HORIZONS_S) -> pl.DataFrame:
    frames = [
        markout_table(aligned, cols, horizons).with_columns(grouping=pl.lit(name))
        for name, cols in GROUPINGS.items()
    ]
    stacked = pl.concat(frames, how="diagonal")
    return stacked.select("grouping", pl.exclude("grouping"))


def exclude_stale(aligned: pl.DataFrame, max_age_s: float = STALE_S) -> pl.DataFrame:
    """Swaps whose time-zero reference trade is at most `max_age_s` old."""
    return aligned.filter(pl.col("cex_age_s_0") <= max_age_s)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_markouts.py -q`
Expected: PASS.

- [ ] **Step 5: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/markouts.py tests/test_markouts.py
git commit -m "Add markouts with notional-weighted tables and day-bootstrap intervals"
git push
```

---

### Task 10: Costs, builder payments and bot profit (`arbprofit.py`)

**Files:**
- Create: `src/uniswap_lp_economics/arbprofit.py`, `tests/test_arbprofit.py`

**Interfaces:**
- Consumes: aligned columns `block_number`, `tx_hash`, `sender`, `flow_label`, `notional_usd`,
  `p_cex_0`, `receipt_gas_used`, `receipt_effective_gas_price`, `markout_usd_0`; `blocks`
  (`block_number`, `miner`, `base_fee_per_gas`); `other_logs` (`tx_hash`, `other_logs`); transfers
  (`TRANSFER_SCHEMA`); series column `available_usd`, `available_usd_cex1bp`.
- Produces:
  - `SINGLE_POOL = "single_pool"`, `MULTI_POOL = "multi_pool"`
  - `tx_scope(other_logs) -> pl.DataFrame` (`tx_hash`, `tx_scope`)
  - `coinbase_payments(transfers, blocks) -> pl.DataFrame` (`tx_hash`, `coinbase_wei`)
  - `add_costs(aligned, blocks, transfers, scope, bots: list[str]) -> pl.DataFrame` adds
    `base_fee_per_gas`, `is_top_bot`, `gas_burned_usd`, `priority_fee_usd`, `coinbase_usd` (null
    outside top bots), `tx_scope` (null outside top bots)
  - `bot_profit_table(aligned) -> pl.DataFrame` (one row per top bot plus `TOTAL`)
  - `waterfall(series, aligned) -> dict[str, float]`

- [ ] **Step 1: Write the tests**

Create `tests/test_arbprofit.py`:

```python
from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics.arbprofit import (
    MULTI_POOL,
    SINGLE_POOL,
    add_costs,
    bot_profit_table,
    tx_scope,
    waterfall,
)
from uniswap_lp_economics.data.transfers import TRANSFER_SCHEMA

BOT = "0x" + "b0" * 20
USER = "0x" + "a1" * 20
ROUTER = "0x" + "c2" * 20
MINER = "0x" + "ee" * 20
GWEI = 10**9
SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "tx_hash": pl.String,
    "sender": pl.String,
    "flow_label": pl.String,
    "notional_usd": pl.Float64,
    "p_cex_0": pl.Float64,
    "receipt_gas_used": pl.Int64,
    "receipt_effective_gas_price": pl.Int64,
    "markout_usd_0": pl.Float64,
}
BLOCKS = pl.DataFrame(
    {"block_number": [1, 2], "miner": [MINER, MINER], "base_fee_per_gas": [20 * GWEI, 20 * GWEI]}
)


def aligned(rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA, orient="row")


def transfers(rows: list[tuple[int, str, str, str, int]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TRANSFER_SCHEMA, orient="row")


def costed() -> pl.DataFrame:
    a = aligned(
        [
            (1, "0xt1", BOT, "searcher", 100.0, 2000.0, 100_000, 30 * GWEI, 3.0),
            (1, "0xt1", BOT, "searcher", 300.0, 2000.0, 100_000, 30 * GWEI, 9.0),
            (2, "0xt2", BOT, "searcher", 50.0, 2000.0, 100_000, 30 * GWEI, 5.0),
            (2, "0xt3", ROUTER, "uniswap_router", 10.0, 2000.0, 100_000, 30 * GWEI, -1.0),
        ]
    )
    t = transfers(
        [
            (1, "0xt1", BOT, MINER, 10**16),  # 0.01 ETH to the fee recipient: 20 USD
            (1, "0xt1", BOT, USER, 10**18),  # not to the miner: ignored
        ]
    )
    scope = tx_scope(pl.DataFrame({"tx_hash": ["0xt1", "0xt2"], "other_logs": [0, 4]}))
    return add_costs(a, BLOCKS, t, scope, [BOT])


def test_costs_split_by_notional_within_tx() -> None:
    c = costed()
    # tx gas: 1e5 gas * 20 gwei base = 0.002 ETH = 4 USD burned; 1e5 * 10 gwei = 2 USD priority.
    assert c["gas_burned_usd"].to_list()[:2] == pytest.approx([1.0, 3.0])
    assert c["priority_fee_usd"].to_list()[:2] == pytest.approx([0.5, 1.5])
    assert c["coinbase_usd"].to_list()[:2] == pytest.approx([5.0, 15.0])
    assert c["gas_burned_usd"].to_list()[3] == pytest.approx(4.0)


def test_scope_and_coinbase_only_for_top_bots() -> None:
    c = costed()
    assert c["is_top_bot"].to_list() == [True, True, True, False]
    assert c["tx_scope"].to_list() == [SINGLE_POOL, SINGLE_POOL, MULTI_POOL, None]
    assert c["coinbase_usd"].to_list()[2:] == [0.0, None]


def test_zero_notional_tx_splits_equally() -> None:
    a = aligned(
        [
            (1, "0xt9", USER, "other_contract", 0.0, 2000.0, 100_000, 20 * GWEI, 0.0),
            (1, "0xt9", USER, "other_contract", 0.0, 2000.0, 100_000, 20 * GWEI, 0.0),
        ]
    )
    c = add_costs(a, BLOCKS, transfers([]), tx_scope(pl.DataFrame(schema={"tx_hash": pl.String, "other_logs": pl.Int64})), [])
    assert c["gas_burned_usd"].to_list() == pytest.approx([2.0, 2.0])


def test_bot_profit_table_and_waterfall() -> None:
    c = costed()
    t = bot_profit_table(c)
    assert t["sender"].to_list() == [BOT, "TOTAL"]
    bot = t.row(0, named=True)
    assert bot["swaps"] == 2 and bot["gross_usd"] == pytest.approx(12.0)
    assert bot["kept_usd"] == pytest.approx(12.0 - 4.0 - 2.0 - 20.0)
    assert bot["builder_usd"] == pytest.approx(22.0)
    assert bot["multi_pool_swaps"] == 1 and bot["multi_pool_gross_usd"] == pytest.approx(5.0)
    assert bot["txs_with_coinbase"] == 1
    series = pl.DataFrame({"available_usd": [30.0, 10.0], "available_usd_cex1bp": [20.0, 5.0]})
    w = waterfall(series, c)
    assert w["available_usd"] == pytest.approx(40.0)
    assert w["captured_searchers_usd"] == pytest.approx(17.0)
    assert w["top_bot_single_pool_gross_usd"] == pytest.approx(12.0)
    assert w["kept_usd"] == pytest.approx(-14.0)


def test_bot_profit_table_without_bots() -> None:
    t = bot_profit_table(costed().with_columns(is_top_bot=pl.lit(False)))
    assert t["sender"].to_list() == ["TOTAL"]
    assert t["gross_usd"].item() == 0.0
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_arbprofit.py -q`
Expected: FAIL (no module `arbprofit`).

- [ ] **Step 3: Implement**

Create `src/uniswap_lp_economics/arbprofit.py`:

```python
"""Arbitrage costs and net profit (spec 5.5).

Per transaction: gas burned (base fee), priority fee and direct coinbase payments, valued at the
Binance price at the block time and split across the transaction's swaps in our pool by
notional. Builder payments are only observed for the top bot contracts; elsewhere they are null.
"""

from typing import Any

import polars as pl

SINGLE_POOL = "single_pool"
MULTI_POOL = "multi_pool"
WEI = 1e18
_COSTS = ["gas_burned_usd", "priority_fee_usd", "coinbase_usd"]


def tx_scope(other_logs: pl.DataFrame) -> pl.DataFrame:
    """single_pool when a top-bot transaction emits no log outside pool/USDC/WETH/the bot."""
    return other_logs.select(
        "tx_hash",
        tx_scope=pl.when(pl.col("other_logs") == 0)
        .then(pl.lit(SINGLE_POOL))
        .otherwise(pl.lit(MULTI_POOL)),
    ).unique("tx_hash", keep="first", maintain_order=True)


def coinbase_payments(transfers: pl.DataFrame, blocks: pl.DataFrame) -> pl.DataFrame:
    """Per transaction: wei the top-bot contracts sent to the block's fee recipient."""
    joined = transfers.join(blocks.select("block_number", "miner"), on="block_number", how="inner")
    return (
        joined.filter(pl.col("to_address") == pl.col("miner"))
        .group_by("tx_hash")
        .agg(coinbase_wei=pl.col("value_wei").sum())
    )


def add_costs(
    aligned: pl.DataFrame,
    blocks: pl.DataFrame,
    transfers: pl.DataFrame,
    scope: pl.DataFrame,
    bots: list[str],
) -> pl.DataFrame:
    a = (
        aligned.join(
            blocks.select("block_number", "base_fee_per_gas"),
            on="block_number",
            how="left",
            maintain_order="left",
        )
        .join(coinbase_payments(transfers, blocks), on="tx_hash", how="left", maintain_order="left")
        .join(scope, on="tx_hash", how="left", maintain_order="left")
    )
    tx_notional = pl.col("notional_usd").sum().over("tx_hash")
    share = (
        pl.when(tx_notional > 0)
        .then(pl.col("notional_usd") / tx_notional)
        .otherwise(1.0 / pl.len().over("tx_hash"))
    )
    eth_usd = pl.col("p_cex_0") / WEI
    gas = pl.col("receipt_gas_used").cast(pl.Float64)
    base = pl.col("base_fee_per_gas").cast(pl.Float64)
    effective = pl.col("receipt_effective_gas_price").cast(pl.Float64)
    is_top = (pl.col("flow_label") == "searcher") & pl.col("sender").is_in(
        pl.Series(bots, dtype=pl.String)
    )
    coinbase = pl.col("coinbase_wei").cast(pl.Float64).fill_null(0.0)
    return a.with_columns(
        is_top_bot=is_top,
        gas_burned_usd=gas * base * eth_usd * share,
        priority_fee_usd=gas * (effective - base) * eth_usd * share,
        coinbase_usd=pl.when(is_top).then(coinbase * eth_usd * share),
        tx_scope=pl.when(is_top).then(pl.col("tx_scope")),
    ).drop("coinbase_wei")


def bot_profit_table(aligned: pl.DataFrame) -> pl.DataFrame:
    """Per top bot and in total: single-pool gross (0s markout) minus gas burned, priority fee
    and coinbase payments = kept; multi-pool transactions reported gross only."""
    bots = aligned.filter(pl.col("is_top_bot"))
    single = bots.filter(pl.col("tx_scope") == SINGLE_POOL).group_by("sender").agg(
        swaps=pl.len().cast(pl.Int64),
        txs=pl.col("tx_hash").n_unique().cast(pl.Int64),
        txs_with_coinbase=pl.col("tx_hash").filter(pl.col("coinbase_usd") > 0).n_unique().cast(pl.Int64),
        notional_usd=pl.col("notional_usd").sum(),
        gross_usd=pl.col("markout_usd_0").sum(),
        **{c: pl.col(c).sum() for c in _COSTS},
    )
    multi = bots.filter(pl.col("tx_scope") == MULTI_POOL).group_by("sender").agg(
        multi_pool_swaps=pl.len().cast(pl.Int64),
        multi_pool_gross_usd=pl.col("markout_usd_0").sum(),
    )
    per_bot = (
        single.join(multi, on="sender", how="full", coalesce=True)
        .fill_null(0)
        .sort(["gross_usd", "sender"], descending=[True, False])
    )
    total = per_bot.select(pl.lit("TOTAL").alias("sender"), pl.exclude("sender").sum())
    table = pl.concat([per_bot, total], how="vertical_relaxed")
    builder = pl.col("priority_fee_usd") + pl.col("coinbase_usd")
    return table.with_columns(
        kept_usd=pl.col("gross_usd") - pl.col("gas_burned_usd") - builder,
        builder_usd=builder,
        builder_share_of_gross=pl.when(pl.col("gross_usd") > 0).then(builder / pl.col("gross_usd")),
    )


def waterfall(series: pl.DataFrame, aligned: pl.DataFrame) -> dict[str, float]:
    """available (all blocks) -> captured by searchers -> top-bot single-pool gross -> costs -> kept."""

    def total(df: pl.DataFrame, col: str) -> float:
        return float(df[col].sum())

    single = aligned.filter(pl.col("is_top_bot") & (pl.col("tx_scope") == SINGLE_POOL))
    gross = total(single, "markout_usd_0")
    burned = total(single, "gas_burned_usd")
    priority = total(single, "priority_fee_usd")
    coinbase = total(single, "coinbase_usd")
    result: dict[str, Any] = {
        "available_usd": total(series, "available_usd"),
        "available_cex1bp_usd": total(series, "available_usd_cex1bp"),
        "captured_searchers_usd": total(
            aligned.filter(pl.col("flow_label") == "searcher"), "markout_usd_0"
        ),
        "top_bot_single_pool_gross_usd": gross,
        "gas_burned_usd": burned,
        "priority_fee_usd": priority,
        "coinbase_usd": coinbase,
        "kept_usd": gross - burned - priority - coinbase,
    }
    return result
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_arbprofit.py -q`
Expected: PASS. If `full` join or `fill_null(0)` changes column dtypes so that the `TOTAL` concat
fails, cast the count columns to `pl.Int64` and the USD columns to `pl.Float64` before the concat;
do not change the test values.

- [ ] **Step 5: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/arbprofit.py tests/test_arbprofit.py
git commit -m "Add gas, builder-payment and net-profit accounting for top bots"
git push
```

---

### Task 11: Per-block series with available arbitrage (`discovery.build_block_series`)

**Files:**
- Create: `src/uniswap_lp_economics/discovery.py`, `tests/test_discovery.py`

**Interfaces:**
- Consumes: `replay.iter_block_starts`, `align.reference_at`, `v3swap.arb_to_price`,
  `v3math.sqrt_price_x96_to_eth_price`.
- Produces:
  - `discovery.FEE_BAND_BP = 5.0`, `EPISODE_THRESHOLDS_BP = (5.0, 10.0)`,
    `CEX_FEE_SENSITIVITY_BP = 1.0`, `SERIES_SCHEMA`
  - `discovery.build_block_series(events, book, fee_protocol, blocks, ref, end_us, fee_pips=FEE_PIPS) -> pl.DataFrame`
    with columns `block_number, block_timestamp, ts_us, sqrt_price_x96 (Int128), tick, liquidity (Int128),
    pool_price, end_sqrt_price_x96 (Int128), end_tick, end_liquidity (Int128), end_pool_price, p_cex,
    cex_age_s, arb_direction, available_usd, available_usd_cex1bp, n_events, n_swaps, basis_bp`

- [ ] **Step 1: Write the test**

Create `tests/test_discovery.py`:

```python
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics.discovery import build_block_series
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import eth_price_to_sqrt_price_x96, get_tick_at_sqrt_ratio

L = 10**18
US = 1_000_000
T0 = datetime(2026, 7, 1, tzinfo=UTC)


def arb_book(price: float) -> TickBook:
    sqrt = eth_price_to_sqrt_price_x96(price)
    tick = get_tick_at_sqrt_ratio(sqrt)
    b = TickBook(tick=tick, sqrt_price_x96=sqrt, liquidity=0)
    b.apply_mint((tick // 10 - 500) * 10, (tick // 10 + 500) * 10, L)
    return b


def blocks_frame(numbers: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "block_number": numbers,
            "block_timestamp": [T0 + timedelta(seconds=12 * i) for i in range(len(numbers))],
        },
        schema={"block_number": pl.Int64, "block_timestamp": pl.Datetime("us", "UTC")},
    )


def swap_events(rows: list[tuple[int, int, float]]) -> pl.DataFrame:
    """(block, log_index, post-swap price) rows as swap events."""
    data: list[dict[str, Any]] = []
    for block, idx, price in rows:
        sqrt = eth_price_to_sqrt_price_x96(price)
        data.append(
            {
                "block_number": block,
                "log_index": idx,
                "event": "swap",
                "tick": get_tick_at_sqrt_ratio(sqrt),
                "sqrt_price_x96": sqrt,
                "liquidity": L,
            }
        )
    return pl.DataFrame(
        data,
        schema={
            "block_number": pl.Int64,
            "log_index": pl.Int64,
            "event": pl.String,
            "tick": pl.Int64,
            "sqrt_price_x96": pl.Int128,
            "liquidity": pl.Int128,
        },
    )


def test_block_series_states_basis_and_available_arbitrage() -> None:
    ref = pl.DataFrame({"ts_us": [int(T0.timestamp()) * US - 1], "price": [2010.0]})
    end_us = int(T0.timestamp()) * US + 3600 * US
    s = build_block_series(
        swap_events([(101, 0, 2009.0)]), arb_book(2000.0), 68, blocks_frame([100, 101, 102, 103]),
        ref, end_us,
    )
    assert s["block_number"].to_list() == [100, 101, 102, 103]
    assert s["n_swaps"].to_list() == [0, 1, 0, 0]
    assert s["pool_price"].to_list() == pytest.approx([2000.0, 2000.0, 2009.0, 2009.0], rel=1e-9)
    assert s["end_pool_price"].to_list() == pytest.approx([2000.0, 2009.0, 2009.0, 2009.0], rel=1e-9)
    assert s["end_sqrt_price_x96"][0] == s["sqrt_price_x96"][1]
    assert s["basis_bp"][0] == pytest.approx(math.log(2000 / 2010) * 1e4, rel=1e-6)
    assert s["arb_direction"].to_list() == ["buy_eth", "buy_eth", "none", "none"]
    avail = s["available_usd"].to_list()
    assert avail[0] > 0 and avail[2] == 0.0
    assert all(a1 <= a0 for a0, a1 in zip(avail, s["available_usd_cex1bp"], strict=True))


def test_block_series_skips_blocks_missing_from_the_block_table() -> None:
    ref = pl.DataFrame({"ts_us": [int(T0.timestamp()) * US - 1], "price": [2000.0]})
    blocks = blocks_frame([100, 101, 102]).filter(pl.col("block_number") != 101)
    s = build_block_series(swap_events([]), arb_book(2000.0), 68, blocks, ref, 10**18)
    assert s["block_number"].to_list() == [100, 102]
    assert s["arb_direction"].to_list() == ["none", "none"]
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: FAIL (no module `discovery`).

- [ ] **Step 3: Implement**

Create `src/uniswap_lp_economics/discovery.py`:

```python
"""Price discovery (spec 6): per-block pool vs Binance series, basis, gap episodes, lead-lag
and available-vs-captured arbitrage."""

from typing import Any

import polars as pl

from uniswap_lp_economics.align import reference_at
from uniswap_lp_economics.config import FEE_PIPS
from uniswap_lp_economics.replay import iter_block_starts
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import sqrt_price_x96_to_eth_price
from uniswap_lp_economics.v3swap import arb_to_price

FEE_BAND_BP = 5.0
EPISODE_THRESHOLDS_BP = (5.0, 10.0)
CEX_FEE_SENSITIVITY_BP = 1.0
SERIES_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "block_timestamp": pl.Datetime("us", "UTC"),
    "ts_us": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "tick": pl.Int64,
    "liquidity": pl.Int128,
    "pool_price": pl.Float64,
    "end_sqrt_price_x96": pl.Int128,
    "end_tick": pl.Int64,
    "end_liquidity": pl.Int128,
    "end_pool_price": pl.Float64,
    "p_cex": pl.Float64,
    "cex_age_s": pl.Float64,
    "arb_direction": pl.String,
    "available_usd": pl.Float64,
    "available_usd_cex1bp": pl.Float64,
}


def build_block_series(
    events: pl.DataFrame,
    book: TickBook,
    fee_protocol: int,
    blocks: pl.DataFrame,
    ref: pl.DataFrame,
    end_us: int,
    fee_pips: int = FEE_PIPS,
) -> pl.DataFrame:
    """One row per block in `blocks` (spec 6.1), with the arbitrage available at its start.

    `book` must hold the pool state at the start of the first block; it is advanced through
    `events` in place. A block missing from `blocks` gets no row (check A2 reports it).
    """
    blocks = blocks.sort("block_number")
    if blocks.height == 0:
        raise ValueError("no blocks to build a series from")
    numbers = blocks["block_number"].to_list()
    ts_us = blocks["block_timestamp"].dt.epoch("us")
    refs = reference_at(ts_us, ref, end_us)
    info = {
        b: (stamp, t, p, age)
        for b, stamp, t, p, age in zip(
            numbers,
            blocks["block_timestamp"].to_list(),
            ts_us.to_list(),
            refs["price"].to_list(),
            refs["age_s"].to_list(),
            strict=True,
        )
    }
    cols: dict[str, list[Any]] = {name: [] for name in SERIES_SCHEMA}
    pending = False
    for b in iter_block_starts(events, book, fee_protocol, numbers[0], numbers[-1]):
        if pending:  # this block's start is the previous block's end
            cols["end_sqrt_price_x96"].append(book.sqrt_price_x96)
            cols["end_tick"].append(book.tick)
            cols["end_liquidity"].append(book.liquidity)
            cols["end_pool_price"].append(sqrt_price_x96_to_eth_price(book.sqrt_price_x96))
            pending = False
        if b not in info:
            continue
        stamp, t, p, age = info[b]
        direction: str | None = None
        avail: float | None = None
        avail_fee: float | None = None
        if p is not None:
            a0 = arb_to_price(book, p, fee_pips)
            a1 = (
                a0
                if a0.direction == "none"
                else arb_to_price(book, p, fee_pips, CEX_FEE_SENSITIVITY_BP)
            )
            direction, avail, avail_fee = a0.direction, a0.profit_usd, a1.profit_usd
        values: dict[str, Any] = {
            "block_number": b,
            "block_timestamp": stamp,
            "ts_us": t,
            "sqrt_price_x96": book.sqrt_price_x96,
            "tick": book.tick,
            "liquidity": book.liquidity,
            "pool_price": sqrt_price_x96_to_eth_price(book.sqrt_price_x96),
            "p_cex": p,
            "cex_age_s": age,
            "arb_direction": direction,
            "available_usd": avail,
            "available_usd_cex1bp": avail_fee,
        }
        for name, value in values.items():
            cols[name].append(value)
        pending = True

    counts = events.group_by("block_number").agg(
        n_events=pl.len().cast(pl.Int64),
        n_swaps=(pl.col("event") == "swap").sum().cast(pl.Int64),
    )
    return (
        pl.DataFrame(cols, schema=SERIES_SCHEMA)
        .join(counts, on="block_number", how="left", maintain_order="left")
        .with_columns(
            pl.col("n_events").fill_null(0),
            pl.col("n_swaps").fill_null(0),
            basis_bp=(pl.col("pool_price") / pl.col("p_cex")).log() * 1e4,
        )
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: PASS.

- [ ] **Step 5: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/discovery.py tests/test_discovery.py
git commit -m "Add per-block pool vs Binance series with available arbitrage"
git push
```

---

### Task 12: Basis, gap episodes, lead-lag, available vs captured

**Files:**
- Modify: `src/uniswap_lp_economics/discovery.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: series from Task 11; swaps with `block_number`, `log_index`, `flow_label`,
  `pre_price_usd`, `price_usd`; aligned with `block_timestamp`, `flow_label`, `markout_usd_0`.
- Produces:
  - `basis_stats(series, band_bp=FEE_BAND_BP) -> dict[str, Any]` (`blocks`, `band_bp`, `mean_bp`,
    `quantiles_bp`, `abs_quantiles_bp`, `share_outside_band`)
  - `find_episodes(series, swaps, k: float) -> pl.DataFrame` (`start_block, end_block, n_blocks,
    start_ts_us, duration_s, peak_abs_bp, gap_weight, closer`)
  - `episode_summary(episodes) -> pl.DataFrame` (`closer, episodes, share_episodes, gap_weight,
    share_gap_weight, median_duration_s`)
  - `cross_correlation(series, max_lag=5) -> pl.DataFrame` (`lag_blocks, corr, n`; positive lag =
    Binance leads)
  - `ar1_half_life(series) -> dict[str, float | None]` (`phi, intercept, half_life_blocks,
    median_block_s, half_life_s`)
  - `available_vs_captured(series, aligned) -> pl.DataFrame` (`day, available_usd,
    available_cex1bp_usd, captured_usd`)

- [ ] **Step 1: Write the tests**

Append to `tests/test_discovery.py` (add `import numpy as np` and import the new functions from
`uniswap_lp_economics.discovery`):

```python
def series_frame(basis: list[float | None], p_cex: float = 2000.0) -> pl.DataFrame:
    n = len(basis)
    return pl.DataFrame(
        {
            "block_number": list(range(1, n + 1)),
            "block_timestamp": [T0 + timedelta(seconds=12 * i) for i in range(n)],
            "ts_us": [int(T0.timestamp()) * US + 12 * US * i for i in range(n)],
            "basis_bp": basis,
            "p_cex": [p_cex] * n,
        },
        schema={
            "block_number": pl.Int64,
            "block_timestamp": pl.Datetime("us", "UTC"),
            "ts_us": pl.Int64,
            "basis_bp": pl.Float64,
            "p_cex": pl.Float64,
        },
    )


def swaps_frame(rows: list[tuple[int, int, str, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "block_number": pl.Int64,
            "log_index": pl.Int64,
            "flow_label": pl.String,
            "pre_price_usd": pl.Float64,
            "price_usd": pl.Float64,
        },
        orient="row",
    )


SWAPS = swaps_frame(
    [
        (3, 0, "other_contract", 2010.0, 2014.0),  # moves away from 2000
        (3, 1, "uniswap_router", 2014.0, 2012.0),  # toward, a little
        (3, 2, "searcher", 2012.0, 2001.0),  # toward, the most
    ]
)


def test_basis_stats() -> None:
    st = basis_stats(series_frame([-10.0, -2.0, 0.0, 3.0, 8.0, None]))
    assert st["blocks"] == 5
    assert st["share_outside_band"] == pytest.approx(0.4)
    assert st["quantiles_bp"]["0.5"] == pytest.approx(0.0)


def test_closer_is_swap_moving_furthest_toward_cex() -> None:
    series = series_frame([0.0, 6.0, 7.0, 2.0, 0.0, 12.0, 11.0, 9.0])
    eps = find_episodes(series, SWAPS, 5.0)
    assert eps["start_block"].to_list() == [2, 6]
    assert eps["end_block"].to_list() == [3, 8]
    assert eps["n_blocks"].to_list() == [2, 3]
    assert eps["closer"].to_list() == ["searcher", "open"]
    assert eps["duration_s"][0] == pytest.approx(24.0)
    assert eps["peak_abs_bp"][0] == pytest.approx(7.0)
    assert eps["gap_weight"][0] == pytest.approx((6.0 + 7.0) * 12)


def test_episode_closed_by_binance_when_no_swap_moves_toward() -> None:
    eps = find_episodes(series_frame([0.0, 6.0, 7.0, 2.0, 0.0, 12.0, 11.0, 9.0]), SWAPS, 10.0)
    assert eps["start_block"].to_list() == [6]
    assert eps["closer"].to_list() == ["cex"]
    summary = episode_summary(eps)
    assert summary["share_episodes"].to_list() == [1.0]


def test_find_episodes_none() -> None:
    eps = find_episodes(series_frame([0.0, 1.0, 2.0]), SWAPS, 5.0)
    assert eps.height == 0
    assert "closer" in eps.columns
    assert episode_summary(eps).height == 0


def test_cross_correlation_finds_binance_lead() -> None:
    rng = np.random.default_rng(1)
    cex = np.cumsum(rng.normal(0.0, 1e-4, 400))
    pool = np.concatenate([[cex[0]], cex[:-1]])  # pool copies Binance one block later
    series = pl.DataFrame(
        {
            "block_number": np.arange(400),
            "pool_price": 2000.0 * np.exp(pool),
            "p_cex": 2000.0 * np.exp(cex),
        }
    )
    xc = cross_correlation(series)
    corr = dict(zip(xc["lag_blocks"], xc["corr"], strict=True))
    assert corr[1] > 0.99
    assert abs(corr[0]) < 0.3
    assert xc["lag_blocks"].to_list() == list(range(-5, 6))


def test_ar1_half_life() -> None:
    rng = np.random.default_rng(2)
    b = np.zeros(20_000)
    for i in range(1, len(b)):
        b[i] = 0.5 * b[i - 1] + rng.normal()
    series = pl.DataFrame(
        {
            "block_number": np.arange(len(b)),
            "ts_us": np.arange(len(b)) * 12 * US,
            "basis_bp": b,
        }
    )
    r = ar1_half_life(series)
    assert r["phi"] == pytest.approx(0.5, abs=0.02)
    assert r["half_life_blocks"] == pytest.approx(1.0, abs=0.1)
    assert r["median_block_s"] == pytest.approx(12.0)
    assert r["half_life_s"] == pytest.approx(12.0, abs=1.2)


def test_available_vs_captured_by_day() -> None:
    series = series_frame([0.0, 0.0]).with_columns(
        available_usd=pl.Series([3.0, 4.0]), available_usd_cex1bp=pl.Series([1.0, 2.0])
    )
    aligned = pl.DataFrame(
        {
            "block_timestamp": [T0, T0],
            "flow_label": ["searcher", "uniswap_router"],
            "markout_usd_0": [2.5, -1.0],
        },
        schema={
            "block_timestamp": pl.Datetime("us", "UTC"),
            "flow_label": pl.String,
            "markout_usd_0": pl.Float64,
        },
    )
    out = available_vs_captured(series, aligned)
    assert out.row(0, named=True)["available_usd"] == pytest.approx(7.0)
    assert out.row(0, named=True)["captured_usd"] == pytest.approx(2.5)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: FAIL (new functions not defined).

- [ ] **Step 3: Implement**

Add `import math` and `import numpy as np` to `src/uniswap_lp_economics/discovery.py`, then append:

```python
QUANTILES = (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
MAX_LAG = 5
_DEFAULT_BLOCK_S = 12.0
EPISODE_SCHEMA: dict[str, Any] = {
    "start_block": pl.Int64,
    "end_block": pl.Int64,
    "n_blocks": pl.Int64,
    "start_ts_us": pl.Int64,
    "duration_s": pl.Float64,
    "peak_abs_bp": pl.Float64,
    "gap_weight": pl.Float64,
    "closer": pl.String,
}


def basis_stats(series: pl.DataFrame, band_bp: float = FEE_BAND_BP) -> dict[str, Any]:
    b = series["basis_bp"].drop_nulls().drop_nans()
    if b.len() == 0:
        return {"blocks": 0, "band_bp": band_bp}
    a = b.abs()
    return {
        "blocks": b.len(),
        "band_bp": band_bp,
        "mean_bp": float(b.mean()),  # type: ignore[arg-type]
        "quantiles_bp": {str(q): float(b.quantile(q)) for q in QUANTILES},  # type: ignore[arg-type]
        "abs_quantiles_bp": {str(q): float(a.quantile(q)) for q in QUANTILES},  # type: ignore[arg-type]
        "share_outside_band": float((a > band_bp).mean()),  # type: ignore[arg-type]
    }


def _closers(series: pl.DataFrame, swaps: pl.DataFrame) -> pl.DataFrame:
    """Per block: flow label of the swap that moved the pool's log price furthest toward Binance."""
    toward = (pl.col("pre_price_usd") / pl.col("p_cex")).log().abs() - (
        pl.col("price_usd") / pl.col("p_cex")
    ).log().abs()
    return (
        swaps.select("block_number", "log_index", "flow_label", "pre_price_usd", "price_usd")
        .join(series.select("block_number", "p_cex"), on="block_number", how="inner")
        .with_columns(toward=toward)
        .filter(pl.col("toward") > 0)
        .sort(["block_number", "toward", "log_index"], descending=[False, True, False])
        .group_by("block_number", maintain_order=True)
        .agg(closer=pl.col("flow_label").first())
    )


def find_episodes(series: pl.DataFrame, swaps: pl.DataFrame, k: float) -> pl.DataFrame:
    """Maximal runs of consecutive blocks with |basis_bp| > k (spec 6.3).

    The episode's last block e is the last one starting outside the band. Its closer is the
    flow label of the swap in e that moved the price furthest toward Binance, "cex" if no swap in
    e did, and "open" if e is the series' last block.
    """
    s = series.sort("block_number").with_columns(
        outside=(pl.col("basis_bp").abs() > k).fill_null(False),
        block_s=((pl.col("ts_us").shift(-1) - pl.col("ts_us")) / 1e6).fill_null(_DEFAULT_BLOCK_S),
    )
    if s.height == 0 or not s["outside"].any():
        return pl.DataFrame(schema=EPISODE_SCHEMA)
    last_block = int(s["block_number"].max())  # type: ignore[arg-type]
    s = s.with_columns(run=(pl.col("outside") != pl.col("outside").shift(1)).fill_null(True).cum_sum())
    eps = (
        s.filter("outside")
        .group_by("run", maintain_order=True)
        .agg(
            start_block=pl.col("block_number").first(),
            end_block=pl.col("block_number").last(),
            n_blocks=pl.len().cast(pl.Int64),
            start_ts_us=pl.col("ts_us").first(),
            end_ts_us=pl.col("ts_us").last(),
            end_block_s=pl.col("block_s").last(),
            peak_abs_bp=pl.col("basis_bp").abs().max(),
            gap_weight=(pl.col("basis_bp").abs() * pl.col("block_s")).sum(),
        )
        .join(_closers(series, swaps), left_on="end_block", right_on="block_number", how="left")
    )
    return eps.select(
        "start_block",
        "end_block",
        "n_blocks",
        "start_ts_us",
        duration_s=(pl.col("end_ts_us") - pl.col("start_ts_us")) / 1e6 + pl.col("end_block_s"),
        peak_abs_bp="peak_abs_bp",
        gap_weight="gap_weight",
        closer=pl.when(pl.col("end_block") == last_block)
        .then(pl.lit("open"))
        .otherwise(pl.coalesce("closer", pl.lit("cex"))),
    ).sort("start_block")


def episode_summary(episodes: pl.DataFrame) -> pl.DataFrame:
    n = max(episodes.height, 1)
    weight = float(episodes["gap_weight"].sum()) or 1.0
    return (
        episodes.group_by("closer")
        .agg(
            episodes=pl.len().cast(pl.Int64),
            gap_weight=pl.col("gap_weight").sum(),
            median_duration_s=pl.col("duration_s").median(),
        )
        .with_columns(
            share_episodes=pl.col("episodes") / n,
            share_gap_weight=pl.col("gap_weight") / weight,
        )
        .select(
            "closer",
            "episodes",
            "share_episodes",
            "gap_weight",
            "share_gap_weight",
            "median_duration_s",
        )
        .sort(["episodes", "closer"], descending=[True, False])
    )


def cross_correlation(series: pl.DataFrame, max_lag: int = MAX_LAG) -> pl.DataFrame:
    """corr(pool_ret[b], cex_ret[b - lag]) for lag in [-max_lag, max_lag] (spec 6.4).

    Returns are per block, from one block's start to the next. A positive lag means Binance
    moved first and the pool followed `lag` blocks later.
    """
    s = series.sort("block_number")
    pool = np.diff(np.log(s["pool_price"].cast(pl.Float64).fill_null(np.nan).to_numpy()))
    cex = np.diff(np.log(s["p_cex"].cast(pl.Float64).fill_null(np.nan).to_numpy()))
    n = len(pool)
    rows: list[dict[str, Any]] = []
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = pool[lag:], cex[: n - lag]
        else:
            x, y = pool[:lag], cex[-lag:]
        mask = np.isfinite(x) & np.isfinite(y)
        corr = math.nan
        if mask.sum() > 2 and np.std(x[mask]) > 0 and np.std(y[mask]) > 0:
            corr = float(np.corrcoef(x[mask], y[mask])[0, 1])
        rows.append({"lag_blocks": lag, "corr": corr, "n": int(mask.sum())})
    return pl.DataFrame(
        rows, schema={"lag_blocks": pl.Int64, "corr": pl.Float64, "n": pl.Int64}
    )


def ar1_half_life(series: pl.DataFrame) -> dict[str, float | None]:
    """OLS fit basis[b+1] = intercept + phi * basis[b]; half-life = ln(0.5) / ln(phi)."""
    s = series.sort("block_number")
    b = s["basis_bp"].cast(pl.Float64).fill_null(np.nan).to_numpy()
    x, y = b[:-1], b[1:]
    mask = np.isfinite(x) & np.isfinite(y)
    block_s = float(np.median(np.diff(s["ts_us"].to_numpy()))) / 1e6 if s.height > 1 else None
    if mask.sum() < 3:
        return {"phi": None, "intercept": None, "half_life_blocks": None,
                "median_block_s": block_s, "half_life_s": None}
    phi, intercept = np.polyfit(x[mask], y[mask], 1)
    half_life = math.log(0.5) / math.log(phi) if 0 < phi < 1 else None
    return {
        "phi": float(phi),
        "intercept": float(intercept),
        "half_life_blocks": half_life,
        "median_block_s": block_s,
        "half_life_s": half_life * block_s if half_life is not None and block_s else None,
    }


def available_vs_captured(series: pl.DataFrame, aligned: pl.DataFrame) -> pl.DataFrame:
    """Daily available arbitrage (block starts) vs searchers' captured 0s markouts."""
    day = pl.col("block_timestamp").dt.date().alias("day")
    available = series.group_by(day).agg(
        available_usd=pl.col("available_usd").sum(),
        available_cex1bp_usd=pl.col("available_usd_cex1bp").sum(),
    )
    captured = (
        aligned.filter(pl.col("flow_label") == "searcher")
        .group_by(day)
        .agg(captured_usd=pl.col("markout_usd_0").sum())
    )
    return (
        available.join(captured, on="day", how="left")
        .with_columns(pl.col("captured_usd").fill_null(0.0))
        .sort("day")
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: PASS.

- [ ] **Step 5: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/discovery.py tests/test_discovery.py
git commit -m "Add basis statistics, gap episodes, lead-lag and available-vs-captured"
git push
```

---

### Task 13: Analysis checks A1–A6 (`checks.py`)

**Files:**
- Create: `src/uniswap_lp_economics/checks.py`, `tests/test_checks.py`
- Modify: `src/uniswap_lp_economics/validate.py` (`write_report` gets `stem` and `title`)

**Interfaces:**
- Consumes: `validate.CheckResult`, `validate.MAX_LISTED`, `replay.iter_swaps_with_pre_state`,
  `replay.required`, `v3swap.check_swap_event`, `v3swap.swap_check_ok`, `flows.label_coverage`,
  `flows.top_unlabelled`, `markouts.STALE_S`, `align.US`.
- Produces:
  - `validate.write_report(results, out_dir, extra, stem: str = "validation_report", title: str = "Validation report") -> str`
  - `checks.check_a1(events, book, fee_protocol) -> CheckResult`
  - `checks.check_a2(series, blocks, events, first_block: int) -> CheckResult`
  - `checks.check_a3(aligned, horizons=HORIZONS_S) -> CheckResult`
  - `checks.check_a4(aligned, ref_first_us: int, end_us: int, horizons=HORIZONS_S) -> CheckResult`
  - `checks.check_a5(labelled) -> CheckResult` (always passes; reported)
  - `checks.check_a6(transfers, aligned, blocks) -> CheckResult` (always passes; reported)
  - `checks.write_checks(results, out_dir, extra) -> str` (writes `analysis_checks.{json,md}`)

- [ ] **Step 1: Write the tests**

Create `tests/test_checks.py`:

```python
import json
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.checks import (
    check_a1,
    check_a2,
    check_a3,
    check_a4,
    write_checks,
)
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import get_amount1_delta, swap_exact_input
from uniswap_lp_economics.validate import CheckResult

L = 10**18
US = 1_000_000
EVENT_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "event": pl.String,
    "tick": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "liquidity": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
}


def book() -> TickBook:
    b = TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0)
    b.apply_mint(-10, 10, L)
    b.apply_mint(10, 20, 2 * L)
    return b


def swap_event(tamper: bool = False) -> pl.DataFrame:
    amount = get_amount1_delta(sqrt_at(0), sqrt_at(10), L, True) * 5 // 4
    r = swap_exact_input(book(), False, amount)
    out = r.amount_out + (r.amount_out // 1000 if tamper else 0)  # tamper: 0.1% more out
    row = {
        "block_number": 1,
        "log_index": 0,
        "event": "swap",
        "tick": r.tick,
        "sqrt_price_x96": r.sqrt_price_x96,
        "liquidity": r.liquidity,
        "amount0": -out,
        "amount1": r.amount_in,
    }
    return pl.DataFrame([row], schema=EVENT_SCHEMA)


def test_a1_passes_on_reproducible_swap_and_fails_on_tampered() -> None:
    ok = check_a1(swap_event(), book(), 0)
    assert ok.passed and ok.summary["bit_exact"] == 1
    bad = check_a1(swap_event(tamper=True), book(), 0)
    assert not bad.passed and bad.summary["outside_tolerance"] == 1


def series(rows: list[tuple[int, int, int, int]]) -> pl.DataFrame:
    """(block, start sqrt, end sqrt, n_events) with constant tick/liquidity."""
    return pl.DataFrame(
        [
            {
                "block_number": b,
                "sqrt_price_x96": s,
                "tick": 0,
                "liquidity": L,
                "end_sqrt_price_x96": e,
                "end_tick": 0,
                "end_liquidity": L,
                "n_events": n,
            }
            for b, s, e, n in rows
        ],
        schema={
            "block_number": pl.Int64,
            "sqrt_price_x96": pl.Int128,
            "tick": pl.Int64,
            "liquidity": pl.Int128,
            "end_sqrt_price_x96": pl.Int128,
            "end_tick": pl.Int64,
            "end_liquidity": pl.Int128,
            "n_events": pl.Int64,
        },
    )


BLOCKS = pl.DataFrame({"block_number": [10, 11, 12]})
EVENTS = pl.DataFrame(
    [{"block_number": 11, "log_index": 0, "event": "swap", "sqrt_price_x96": 7}],
    schema={"block_number": pl.Int64, "log_index": pl.Int64, "event": pl.String,
            "sqrt_price_x96": pl.Int128},
)


def test_a2_complete_and_consistent() -> None:
    good = series([(10, 5, 5, 0), (11, 5, 7, 1), (12, 7, 7, 0)])
    assert check_a2(good, BLOCKS, EVENTS, 10).passed
    assert not check_a2(good.filter(pl.col("block_number") != 11), BLOCKS, EVENTS, 10).passed
    assert not check_a2(series([(10, 5, 5, 0), (11, 5, 8, 1), (12, 8, 8, 0)]), BLOCKS, EVENTS, 10).passed
    assert not check_a2(series([(10, 5, 6, 0), (11, 6, 7, 1), (12, 7, 7, 0)]), BLOCKS, EVENTS, 10).passed
    assert not check_a2(good, BLOCKS, EVENTS, 9).passed  # block table starts too late


def test_a3_identity() -> None:
    df = pl.DataFrame(
        {"markout_usd_0": [9.0, -1.0], "lp_markout_usd_0": [-9.25, 0.75], "protocol_fee_usd": [0.25, 0.25]}
    )
    assert check_a3(df, (0,)).passed
    assert not check_a3(df.with_columns(protocol_fee_usd=pl.lit(0.5)), (0,)).passed


def test_a4_nulls_only_past_the_data_end() -> None:
    end = 100 * US
    df = pl.DataFrame(
        {
            "t0_us": [10 * US, 95 * US],
            "p_cex_0": [1.0, 1.0],
            "p_cex_12": [1.0, None],  # 95 s + 12 s is past the end: allowed
            "cex_age_s_0": [0.1, 6.0],
        }
    )
    ok = check_a4(df, 0, end, (0, 12))
    assert ok.passed and ok.summary["stale_ref_over_5s_at_0s"] == 1
    bad = df.with_columns(p_cex_0=pl.Series([None, 1.0], dtype=pl.Float64))
    assert not check_a4(bad, 0, end, (0, 12)).passed


def test_write_checks(tmp_path: Path) -> None:
    status = write_checks([CheckResult("A1", True, {"n": 1})], tmp_path, {"git_commit": "x"})
    assert status == "PASS"
    body = json.loads((tmp_path / "analysis_checks.json").read_text())
    assert body["status"] == "PASS" and body["git_commit"] == "x"
    assert (tmp_path / "analysis_checks.md").read_text().startswith("# Analysis checks: **PASS**")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_checks.py -q`
Expected: FAIL (no module `checks`).

- [ ] **Step 3: Generalise `write_report`**

In `src/uniswap_lp_economics/validate.py`, change the signature to
`def write_report(results: list[CheckResult], out_dir: Path, extra: dict[str, Any], stem: str = "validation_report", title: str = "Validation report") -> str:`,
write to `out_dir / f"{stem}.json"` and `out_dir / f"{stem}.md"`, and make the first markdown line
`f"# {title}: **{status}**"`. Existing callers keep the defaults.

- [ ] **Step 4: Implement `checks.py`**

Create `src/uniswap_lp_economics/checks.py`:

```python
"""Analysis checks A1-A6 (spec 7). A1-A4 gate `ulpe analyze`; A5 and A6 are reported only."""

from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics import flows
from uniswap_lp_economics.align import US
from uniswap_lp_economics.config import HORIZONS_S
from uniswap_lp_economics.markouts import STALE_S
from uniswap_lp_economics.replay import iter_swaps_with_pre_state, required
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3swap import check_swap_event, swap_check_ok
from uniswap_lp_economics.validate import MAX_LISTED, CheckResult, write_report

A3_TOL_USD = 1e-6


def check_a1(events: pl.DataFrame, book: TickBook, fee_protocol: int) -> CheckResult:
    """Every historical swap re-simulated from its replayed pre-swap state (plan Ruling 2)."""
    n = exact = bad = skipped = 0
    worst_sqrt, worst_out = 0.0, 0
    listed: list[dict[str, Any]] = []
    for row in iter_swaps_with_pre_state(events, book, fee_protocol):
        c = check_swap_event(
            book,
            required(row, "amount0"),
            required(row, "amount1"),
            required(row, "sqrt_price_x96"),
        )
        if c is None:
            skipped += 1
            continue
        n += 1
        exact += c.exact
        worst_sqrt = max(worst_sqrt, c.sqrt_rel_err)
        worst_out = max(worst_out, c.out_abs_err)
        if not swap_check_ok(c):
            bad += 1
            if len(listed) < MAX_LISTED:
                listed.append(
                    {
                        "block": row.block_number,
                        "log_index": row.log_index,
                        "sqrt_rel_err": c.sqrt_rel_err,
                        "out_abs_err": c.out_abs_err,
                        "out_expected": c.out_expected,
                    }
                )
    return CheckResult(
        "A1 v3swap reproduces every swap",
        bad == 0 and n > 0,
        {
            "swaps": n,
            "bit_exact": exact,
            "outside_tolerance": bad,
            "no_input_skipped": skipped,
            "max_sqrt_rel_err": worst_sqrt,
            "max_out_abs_err": worst_out,
        },
        listed,
    )


def check_a2(
    series: pl.DataFrame, blocks: pl.DataFrame, events: pl.DataFrame, first_block: int
) -> CheckResult:
    """Block series complete and consistent (plan Ruling 3)."""
    last = int(blocks["block_number"].max()) if blocks.height else first_block - 1  # type: ignore[arg-type]
    expected = set(range(first_block, last + 1))
    present = set(series["block_number"].to_list())
    missing = len(expected - present)
    dupes = series.height - series["block_number"].n_unique()
    first_ok = blocks.height > 0 and int(blocks["block_number"].min()) == first_block  # type: ignore[arg-type]
    state = ["sqrt_price_x96", "tick", "liquidity"]
    s = series.sort("block_number").with_columns(
        prev_block=pl.col("block_number").shift(1),
        **{f"prev_end_{c}": pl.col(f"end_{c}").shift(1) for c in state},
    )
    differs_from_prev = pl.any_horizontal([pl.col(c) != pl.col(f"prev_end_{c}") for c in state])
    bad_continuity = s.filter(
        (pl.col("block_number") - pl.col("prev_block") == 1) & differs_from_prev
    ).height
    last_swap = (
        events.filter(pl.col("event") == "swap")
        .sort("block_number", "log_index")
        .group_by("block_number", maintain_order=True)
        .agg(last_sqrt=pl.col("sqrt_price_x96").last())
    )
    bad_end = (
        s.join(last_swap, on="block_number", how="inner")
        .filter(pl.col("end_sqrt_price_x96") != pl.col("last_sqrt"))
        .height
    )
    changed = pl.any_horizontal([pl.col(c) != pl.col(f"end_{c}") for c in state])
    bad_idle = s.filter((pl.col("n_events") == 0) & changed).height
    passed = (
        series.height > 0
        and first_ok
        and missing == 0
        and dupes == 0
        and bad_continuity == 0
        and bad_end == 0
        and bad_idle == 0
    )
    return CheckResult(
        "A2 block series complete and consistent",
        passed,
        {
            "blocks": series.height,
            "expected_blocks": len(expected),
            "missing": missing,
            "duplicates": dupes,
            "block_table_starts_at_first_block": first_ok,
            "start_differs_from_previous_end": bad_continuity,
            "end_differs_from_last_swap": bad_end,
            "idle_blocks_changed": bad_idle,
        },
    )


def check_a3(aligned: pl.DataFrame, horizons: tuple[int, ...] = HORIZONS_S) -> CheckResult:
    worst, values = 0.0, 0
    for h in horizons:
        resid = (
            pl.col(f"markout_usd_{h}") + pl.col(f"lp_markout_usd_{h}") + pl.col("protocol_fee_usd")
        ).abs()
        m, cnt = aligned.select(
            resid.max().alias("worst"),
            pl.col(f"markout_usd_{h}").is_not_null().sum().alias("values"),
        ).row(0)
        worst = max(worst, float(m or 0.0))
        values += int(cnt)
    return CheckResult(
        "A3 trader + LP + protocol fee = 0",
        worst < A3_TOL_USD and values > 0,
        {"values_checked": values, "max_abs_residual_usd": worst, "tolerance_usd": A3_TOL_USD},
    )


def check_a4(
    aligned: pl.DataFrame,
    ref_first_us: int,
    end_us: int,
    horizons: tuple[int, ...] = HORIZONS_S,
) -> CheckResult:
    """A reference may be missing only outside the Binance data (plan Ruling 6)."""
    summary: dict[str, Any] = {}
    unexpected = 0
    for h in horizons:
        t = pl.col("t0_us") + h * US
        null = pl.col(f"p_cex_{h}").is_null()
        allowed = (t >= end_us) | (t < ref_first_us)
        n_null = aligned.filter(null).height
        bad = aligned.filter(null & ~allowed).height
        summary[f"null_{h}s"] = n_null
        summary[f"unexpected_null_{h}s"] = bad
        unexpected += bad
    summary["stale_ref_over_5s_at_0s"] = aligned.filter(pl.col("cex_age_s_0") > STALE_S).height
    return CheckResult(
        "A4 Binance reference coverage", unexpected == 0 and aligned.height > 0, summary
    )


def check_a5(labelled: pl.DataFrame) -> CheckResult:
    cov = flows.label_coverage(labelled)
    share = dict(zip(cov["flow_label"].to_list(), cov["notional_share"].to_list(), strict=True))
    top = flows.top_unlabelled(labelled, "to_address", 5)
    return CheckResult(
        "A5 label coverage (reported)",
        True,
        {"other_contract_notional_share": share.get("other_contract", 0.0), "by_label": share},
        top.to_dicts(),
    )


def check_a6(transfers: pl.DataFrame, aligned: pl.DataFrame, blocks: pl.DataFrame) -> CheckResult:
    bot = aligned.filter(pl.col("is_top_bot"))
    bot_txs = bot["tx_hash"].unique()
    in_bot_txs = transfers.filter(pl.col("tx_hash").is_in(bot_txs)).join(
        blocks.select("block_number", "miner"), on="block_number", how="left"
    )
    to_miner = in_bot_txs.filter(pl.col("to_address") == pl.col("miner")).height
    with_payment = bot.filter(pl.col("coinbase_usd") > 0)["tx_hash"].n_unique()
    n_txs = bot_txs.len()
    return CheckResult(
        "A6 builder payments (reported)",
        True,
        {
            "top_bot_txs": n_txs,
            "transfers_to_miner": to_miner,
            "transfers_to_others": in_bot_txs.height - to_miner,
            "txs_with_coinbase_payment": with_payment,
            "share_txs_with_coinbase_payment": with_payment / n_txs if n_txs else None,
            "top_bot_txs_without_scope": bot.filter(pl.col("tx_scope").is_null())[
                "tx_hash"
            ].n_unique(),
        },
    )


def write_checks(results: list[CheckResult], out_dir: Path, extra: dict[str, Any]) -> str:
    return write_report(results, out_dir, extra, stem="analysis_checks", title="Analysis checks")
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_checks.py tests/test_validate.py -q`
Expected: PASS.

- [ ] **Step 6: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/checks.py src/uniswap_lp_economics/validate.py tests/test_checks.py
git commit -m "Add analysis checks A1-A6"
git push
```

---

### Task 14: Tables, summary and charts (`report.py`, `figures.py`)

**Files:**
- Create: `src/uniswap_lp_economics/report.py`, `src/uniswap_lp_economics/figures.py`,
  `tests/test_report.py`, `tests/test_figures.py`

**Interfaces:**
- Consumes: `io.write_text_atomic`, `config.HORIZONS_S`.
- Produces:
  - `report.LIMITATION_TEXT: str` (spec section 9, verbatim)
  - `report.markdown_table(df, digits=2) -> str`, `report.metrics_table(metrics: dict) -> pl.DataFrame`
  - `report.write_table(df, out_dir, stem, title, notes: list[str] | None = None, digits=2) -> None`
    (writes `stem.csv` and `stem.md`)
  - `report.write_markdown(out_dir, stem, title, sections: list[tuple[str, pl.DataFrame]], notes=None, digits=2) -> None`
  - `report.write_summary(summary: dict, out_dir) -> None` (`summary.json`; non-finite floats → null,
    dates → ISO strings)
  - `figures.markout_curves(by_label, path)`, `figures.basis_histogram(series, path, band_bp)`,
    `figures.episode_chart(episodes, summary, path)`, `figures.waterfall_chart(w, path)`,
    `figures.cross_correlation_chart(xc, path)`, `figures.bot_profit_chart(bot_profit, path)`

- [ ] **Step 1: Write the tests**

Create `tests/test_report.py`:

```python
import json
import math
from datetime import date
from pathlib import Path

import polars as pl

from uniswap_lp_economics.report import (
    LIMITATION_TEXT,
    markdown_table,
    metrics_table,
    write_summary,
    write_table,
)


def test_markdown_table_formats_values() -> None:
    df = pl.DataFrame({"name": ["a", None], "n": [1234567, 2], "x": [1.23456, math.nan]})
    assert markdown_table(df).splitlines() == [
        "| name | n | x |",
        "|---|---|---|",
        "| a | 1,234,567 | 1.23 |",
        "|  | 2 |  |",
    ]
    assert markdown_table(df.head(0)).splitlines() == ["| name | n | x |", "|---|---|---|"]


def test_metrics_table_flattens_nested_dicts() -> None:
    t = metrics_table({"blocks": 3, "quantiles_bp": {"0.5": 1.5}})
    assert t.rows() == [("blocks", "3"), ("quantiles_bp.0.5", "1.5000")]


def test_write_table_writes_csv_and_markdown_with_notes(tmp_path: Path) -> None:
    write_table(pl.DataFrame({"a": [1]}), tmp_path, "t", "Title", notes=[LIMITATION_TEXT])
    assert (tmp_path / "t.csv").read_text().splitlines() == ["a", "1"]
    md = (tmp_path / "t.md").read_text()
    assert md.startswith("# Title") and "upper bound" in md and "| a |" in md


def test_write_summary_cleans_values(tmp_path: Path) -> None:
    write_summary({"x": math.inf, "y": [math.nan, 1.0], "d": date(2026, 7, 1)}, tmp_path)
    assert json.loads((tmp_path / "summary.json").read_text()) == {
        "x": None,
        "y": [None, 1.0],
        "d": "2026-07-01",
    }
```

Create `tests/test_figures.py`:

```python
from pathlib import Path

import polars as pl

from uniswap_lp_economics import figures

BY_LABEL = pl.DataFrame(
    {
        "flow_label": ["searcher", "searcher", "uniswap_router", "uniswap_router"],
        "horizon_s": [0, 12, 0, 12],
        "mean_bp": [2.0, 1.0, -3.0, None],
        "ci_lo_bp": [1.5, 0.5, -4.0, None],
        "ci_hi_bp": [2.5, 1.5, -2.0, None],
    }
)
SERIES = pl.DataFrame({"basis_bp": [-3.0, 0.0, 7.0, None]})
EPISODES = pl.DataFrame({"duration_s": [12.0, 24.0, 120.0]})
SUMMARY = pl.DataFrame({"closer": ["searcher", "cex"], "share_gap_weight": [0.8, 0.2]})
WATERFALL = {
    "available_usd": 2e6,
    "captured_searchers_usd": 1.5e6,
    "top_bot_single_pool_gross_usd": 1e6,
    "gas_burned_usd": 1e5,
    "priority_fee_usd": 2e5,
    "coinbase_usd": 5e5,
    "kept_usd": 2e5,
}
XC = pl.DataFrame({"lag_blocks": [-1, 0, 1], "corr": [0.0, 0.1, 0.9]})
BOTS = pl.DataFrame(
    {"sender": ["0x" + "b0" * 20, "TOTAL"], "gross_usd": [5e4, 5e4], "kept_usd": [1e4, 1e4]}
)


def _draw_all(tmp_path: Path, by_label: pl.DataFrame, series: pl.DataFrame,
              episodes: pl.DataFrame, summary: pl.DataFrame, w: dict[str, float],
              xc: pl.DataFrame, bots: pl.DataFrame) -> list[Path]:
    paths = [tmp_path / f"{i}.png" for i in range(1, 7)]
    figures.markout_curves(by_label, paths[0])
    figures.basis_histogram(series, paths[1], 5.0)
    figures.episode_chart(episodes, summary, paths[2])
    figures.waterfall_chart(w, paths[3])
    figures.cross_correlation_chart(xc, paths[4])
    figures.bot_profit_chart(bots, paths[5])
    return paths


def test_figures_write_pngs(tmp_path: Path) -> None:
    for p in _draw_all(tmp_path, BY_LABEL, SERIES, EPISODES, SUMMARY, WATERFALL, XC, BOTS):
        assert p.stat().st_size > 1000, p


def test_figures_handle_empty_inputs(tmp_path: Path) -> None:
    paths = _draw_all(
        tmp_path,
        BY_LABEL.head(0),
        SERIES.head(0),
        EPISODES.head(0),
        SUMMARY.head(0),
        {},
        XC.head(0),
        BOTS.head(0),
    )
    assert all(p.exists() for p in paths)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_report.py tests/test_figures.py -q`
Expected: FAIL (no modules `report`, `figures`).

- [ ] **Step 3: Implement `report.py`**

Create `src/uniswap_lp_economics/report.py`:

```python
"""Tables and the summary for results/: CSV + markdown pairs, and summary.json."""

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.io import write_text_atomic

LIMITATION_TEXT = (
    "Builder payments are detected only as direct ETH transfers from the bot contract to the "
    "block's fee recipient within the same transaction. Payments routed elsewhere (another "
    "contract, a separate transaction in the bundle, off-chain agreements) are missed, so the "
    "reported net profit is an **upper bound** on what the bots keep. Binance-side trading fees, "
    "inventory and hedging costs are not observed."
)


def _fmt(value: object, digits: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return "" if math.isnan(value) else f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def markdown_table(df: pl.DataFrame, digits: int = 2) -> str:
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(_fmt(v, digits) for v in row) + " |" for row in df.iter_rows()]
    return "\n".join(lines) + "\n"


def metrics_table(metrics: dict[str, Any]) -> pl.DataFrame:
    """Flatten a nested dict into (metric, value) rows; nested keys are joined with dots."""
    rows: list[tuple[str, str]] = []

    def walk(prefix: str, obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        else:
            rows.append((prefix, _fmt(obj, 4)))

    walk("", metrics)
    return pl.DataFrame(rows, schema={"metric": pl.String, "value": pl.String}, orient="row")


def write_markdown(
    out_dir: Path,
    stem: str,
    title: str,
    sections: list[tuple[str, pl.DataFrame]],
    notes: list[str] | None = None,
    digits: int = 2,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = [f"# {title}", ""]
    for note in notes or []:
        parts += [note, ""]
    for heading, df in sections:
        if heading:
            parts += [f"## {heading}", ""]
        parts += [markdown_table(df, digits)]
    write_text_atomic(out_dir / f"{stem}.md", "\n".join(parts))


def write_table(
    df: pl.DataFrame,
    out_dir: Path,
    stem: str,
    title: str,
    notes: list[str] | None = None,
    digits: int = 2,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    df.write_csv(out_dir / f"{stem}.csv")
    write_markdown(out_dir, stem, title, [("", df)], notes, digits)


def _clean(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, date):  # datetime is a date too
        return obj.isoformat()
    return obj


def write_summary(summary: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_text_atomic(out_dir / "summary.json", json.dumps(_clean(summary), indent=2) + "\n")
```

- [ ] **Step 4: Implement `figures.py`**

Create `src/uniswap_lp_economics/figures.py`:

```python
"""Charts for results/figures (spec section 8). Every chart renders, even from empty input
(a "no data" panel), so a quiet sub-sample never breaks `ulpe analyze`."""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from uniswap_lp_economics.config import HORIZONS_S  # noqa: E402

HORIZON_LABELS = {0: "0s", 12: "12s", 60: "1m", 300: "5m", 3600: "1h"}
WATERFALL_STEPS = [
    ("available_usd", "available"),
    ("captured_searchers_usd", "captured\n(searchers)"),
    ("top_bot_single_pool_gross_usd", "top bots\nsingle-pool gross"),
    ("gas_burned_usd", "- base fee\nburned"),
    ("priority_fee_usd", "- priority\nfee"),
    ("coinbase_usd", "- coinbase\npayment"),
    ("kept_usd", "kept\n(upper bound)"),
]


def _save(fig: Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _no_data(ax: Axes) -> None:
    ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)


def _floats(s: pl.Series) -> list[float]:
    return [math.nan if v is None else float(v) for v in s.to_list()]


def markout_curves(by_label: pl.DataFrame, path: Path) -> None:
    """Chart 1 (headline): notional-weighted trader markout by flow label, with 95% bands."""
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = sorted(set(by_label["flow_label"].to_list())) if by_label.height else []
    for label in labels:
        g = by_label.filter(pl.col("flow_label") == label).sort("horizon_s")
        x = [HORIZONS_S.index(h) for h in g["horizon_s"].to_list()]
        ax.plot(x, _floats(g["mean_bp"]), marker="o", label=label)
        ax.fill_between(x, _floats(g["ci_lo_bp"]), _floats(g["ci_hi_bp"]), alpha=0.15)
    if labels:
        ax.legend(title="flow")
    else:
        _no_data(ax)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_xticks(range(len(HORIZONS_S)), [HORIZON_LABELS.get(h, f"{h}s") for h in HORIZONS_S])
    ax.set_xlabel("time after the block")
    ax.set_ylabel("trader markout vs Binance (bp of notional)")
    ax.set_title("Who wins against the pool? Markouts by flow type (95% day-bootstrap bands)")
    _save(fig, path)


def basis_histogram(series: pl.DataFrame, path: Path, band_bp: float) -> None:
    """Chart 2: pool vs Binance basis at block start, with the fee band."""
    fig, ax = plt.subplots(figsize=(8, 5))
    b = series["basis_bp"].drop_nulls().drop_nans().clip(-50.0, 50.0).to_numpy()
    if len(b):
        ax.hist(b, bins=200, color="tab:blue")
    else:
        _no_data(ax)
    for x in (-band_bp, band_bp):
        ax.axvline(x, color="tab:red", ls="--", lw=1)
    ax.set_xlabel("basis at block start (bp, clipped to +/-50)")
    ax.set_ylabel("blocks")
    ax.set_title(f"How far apart are the venues? Dashed: +/-{band_bp:g} bp fee band")
    _save(fig, path)


def episode_chart(episodes: pl.DataFrame, summary: pl.DataFrame, path: Path) -> None:
    """Chart 3: how long gap episodes last, and who closes them."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    d = np.sort(episodes["duration_s"].drop_nulls().to_numpy()) if episodes.height else []
    if len(d):
        ax1.step(d, 1.0 - np.arange(1, len(d) + 1) / len(d), where="post")
        ax1.set_xscale("log")
    else:
        _no_data(ax1)
    ax1.set_xlabel("episode duration (s)")
    ax1.set_ylabel("share of episodes lasting longer")
    ax1.set_title("How long do gaps last?")
    if summary.height:
        ax2.bar(summary["closer"].to_list(), _floats(summary["share_gap_weight"]), color="tab:orange")
        ax2.tick_params(axis="x", rotation=30)
    else:
        _no_data(ax2)
    ax2.set_ylabel("share of gap-weighted time")
    ax2.set_title("Who closes the gap?")
    _save(fig, path)


def waterfall_chart(w: dict[str, float], path: Path) -> None:
    """Chart 4: available -> captured -> costs -> kept."""
    fig, ax = plt.subplots(figsize=(11, 5))
    values = []
    for key, _ in WATERFALL_STEPS:
        v = w.get(key)
        values.append(v / 1e6 if v is not None and math.isfinite(v) else 0.0)
    colors = ["tab:blue"] * 3 + ["tab:red"] * 3 + ["tab:green"]
    names = [label for _, label in WATERFALL_STEPS]
    ax.bar(names, values, color=colors)
    for i, v in enumerate(values):
        ax.annotate(f"{v:,.2f}", (i, v), ha="center", va="bottom", fontsize=8)
    if not w:
        _no_data(ax)
    ax.set_ylabel("USD millions")
    ax.set_title("Arbitrage: available -> captured -> kept after gas and builder payments")
    _save(fig, path)


def cross_correlation_chart(xc: pl.DataFrame, path: Path) -> None:
    """Chart 5: correlation of pool returns with lagged Binance returns."""
    fig, ax = plt.subplots(figsize=(8, 5))
    if xc.height:
        ax.bar(xc["lag_blocks"].to_list(), _floats(xc["corr"]), color="tab:purple")
    else:
        _no_data(ax)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_xlabel("lag (blocks); positive = Binance moved first")
    ax.set_ylabel("correlation of per-block log returns")
    ax.set_title("Lead-lag: pool vs Binance")
    _save(fig, path)


def bot_profit_chart(bot_profit: pl.DataFrame, path: Path) -> None:
    """Chart 6: gross vs kept per top bot (single-pool transactions)."""
    fig, ax = plt.subplots(figsize=(11, 5))
    bots = bot_profit.filter(pl.col("sender") != "TOTAL") if bot_profit.height else bot_profit
    if bots.height:
        x = np.arange(bots.height)
        ax.bar(x - 0.2, [v / 1e3 for v in _floats(bots["gross_usd"])], width=0.4, label="gross")
        ax.bar(x + 0.2, [v / 1e3 for v in _floats(bots["kept_usd"])], width=0.4, label="kept")
        short = [f"{a[:6]}...{a[-4:]}" for a in bots["sender"].to_list()]
        ax.set_xticks(x, short, rotation=45, ha="right")
        ax.legend()
    else:
        _no_data(ax)
    ax.axhline(0.0, color="grey", lw=0.8)
    ax.set_ylabel("USD thousands")
    ax.set_title("Top bots: gross 0s markout vs kept (upper bound), single-pool transactions")
    _save(fig, path)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_report.py tests/test_figures.py -q`
Expected: PASS.

- [ ] **Step 6: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/report.py src/uniswap_lp_economics/figures.py tests/test_report.py tests/test_figures.py
git commit -m "Add results tables, summary writer and the six charts"
git push
```

---

### Task 15: `ulpe analyze` (`analyze.py`)

**Files:**
- Create: `src/uniswap_lp_economics/analyze.py`, `tests/test_analyze.py`
- Modify: `src/uniswap_lp_economics/config.py`, `src/uniswap_lp_economics/validate.py`
  (`git_commit`), `src/uniswap_lp_economics/cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `config.PROCESSED_DIR = DATA_DIR / "processed"`, `config.RESULTS_DIR = ROOT / "results"`
  - `validate.git_commit() -> str`
  - `analyze.Inputs` (dataclass: `events, swaps, trades, klines, ticks, meta, blocks, other_logs,
    transfers, labels, bots`)
  - `analyze.load_inputs(raw: Path, interim: Path, labels_csv: Path) -> Inputs`
  - `analyze.build_aligned(labelled, ref, end_us, inp, shift_s=0.0) -> pl.DataFrame`
  - `analyze.analyze(inp, results_dir, processed_dir, provenance, end_us=None) -> str`
  - `analyze.run_analysis() -> str`; CLI `ulpe analyze`

- [ ] **Step 1: Write the tests**

Create `tests/test_analyze.py`:

```python
import json
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics import analyze as analysis
from uniswap_lp_economics import config, flows
from uniswap_lp_economics.build import build_swaps
from uniswap_lp_economics.data.transfers import TRANSFER_SCHEMA
from uniswap_lp_economics.io import read_exact, write_exact

FIX = Path(__file__).parent / "fixtures"
MINER = "0x" + "ee" * 20
US = 1_000_000


def fixture_inputs() -> tuple[analysis.Inputs, int]:
    """The real 400-event fixture plus synthetic blocks, Binance prices and bot data."""
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    events = read_exact(FIX / "fixture_events.parquet")
    swaps = build_swaps(events, int(meta["sqrt_price_x96"]), int(meta["fee_protocol"]))
    labels = flows.load_labels(config.LABELS_CSV)
    bots = flows.top_bots(flows.label_swaps(swaps, labels))

    first = int(meta["block"]) + 1
    last = int(events["block_number"].max())  # type: ignore[arg-type]
    stamps = events.group_by("block_number").agg(pl.col("block_timestamp").first())
    blocks = (
        pl.DataFrame({"block_number": list(range(first, last + 1))}, schema={"block_number": pl.Int64})
        .join(stamps, on="block_number", how="left", maintain_order="left")
        .with_columns(
            pl.col("block_timestamp").fill_null(strategy="forward"),
            miner=pl.lit(MINER),
            base_fee_per_gas=pl.lit(10**9, dtype=pl.Int64),
        )
    )

    ts = events["block_timestamp"].dt.epoch("us")
    t_first, t_last = int(ts.min()), int(ts.max())  # type: ignore[arg-type]
    seconds = pl.DataFrame({"ts_us": list(range(t_first - 60 * US, t_last + 3700 * US, US))})
    pool = swaps.select(ts_us=pl.col("block_timestamp").dt.epoch("us"), px=pl.col("price_usd"))
    trades = (
        seconds.join_asof(pool.sort("ts_us"), on="ts_us", strategy="backward")
        .with_columns(price=pl.col("px").fill_null(strategy="backward") * 1.0003)
        .select("ts_us", "price", qty=pl.lit(1.0), is_buyer_maker=pl.lit(True))
    )
    klines = trades.select("ts_us", close="price")

    bot_txs = swaps.filter(pl.col("to_address").is_in(bots))["tx_hash"].unique().sort().to_list()
    assert len(bot_txs) >= 2
    other_logs = pl.DataFrame(
        {"tx_hash": bot_txs, "other_logs": [3] + [0] * (len(bot_txs) - 1)},
        schema={"tx_hash": pl.String, "other_logs": pl.Int64},
    )
    paid = swaps.filter(pl.col("tx_hash") == bot_txs[1]).row(0, named=True)
    transfers = pl.DataFrame(
        [(paid["block_number"], paid["tx_hash"], paid["to_address"], MINER, 10**15)],
        schema=TRANSFER_SCHEMA,
        orient="row",
    )
    inp = analysis.Inputs(
        events=events,
        swaps=swaps,
        trades=trades,
        klines=klines,
        ticks=read_exact(FIX / "fixture_ticks.parquet"),
        meta=meta,
        blocks=blocks,
        other_logs=other_logs,
        transfers=transfers,
        labels=labels,
        bots=bots,
    )
    return inp, t_last + 3700 * US


def test_analyze_fixture_end_to_end(tmp_path: Path) -> None:
    inp, end_us = fixture_inputs()
    results, processed = tmp_path / "results", tmp_path / "processed"
    status = analysis.analyze(inp, results, processed, {"git_commit": "test"}, end_us=end_us)
    assert status == "PASS", (results / "analysis_checks.md").read_text()
    for name in (
        "summary.json",
        "markouts.csv",
        "markouts.md",
        "markouts_robustness.csv",
        "markouts_robustness.md",
        "labels_coverage.md",
        "basis.md",
        "episodes.csv",
        "episodes.md",
        "leadlag.md",
        "arbitrage.md",
        "bot_profit.csv",
        "bot_profit.md",
    ):
        assert (results / name).exists(), name
    assert len(list((results / "figures").glob("*.png"))) == 6
    summary = json.loads((results / "summary.json").read_text())
    assert summary["swaps"] == inp.swaps.height
    assert summary["git_commit"] == "test"
    assert "upper bound" in summary["limitation"]
    for name in ("arbitrage.md", "bot_profit.md"):
        assert "upper bound" in (results / name).read_text()
    assert (processed / "aligned.parquet").exists()
    assert (processed / "blocks_state.parquet").exists()


def test_load_inputs_names_the_missing_fetch(tmp_path: Path) -> None:
    raw, interim = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    interim.mkdir()
    meta = json.loads((FIX / "fixture_meta.json").read_text())
    events = read_exact(FIX / "fixture_events.parquet")
    swaps = build_swaps(events, int(meta["sqrt_price_x96"]), int(meta["fee_protocol"]))
    write_exact(swaps, interim / "swaps.parquet")
    with pytest.raises(FileNotFoundError, match="ulpe fetch-blocks"):
        analysis.load_inputs(raw, interim, config.LABELS_CSV)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_analyze.py -q`
Expected: FAIL (no module `analyze`).

- [ ] **Step 3: Config, `git_commit`, and `analyze.py`**

Add to `src/uniswap_lp_economics/config.py` (after `INTERIM_DIR`):

```python
PROCESSED_DIR = DATA_DIR / "processed"
RESULTS_DIR = ROOT / "results"
```

In `src/uniswap_lp_economics/validate.py`, add and use it in `run_validation` (replace the inline
`subprocess.run` and `commit or "unknown"`):

```python
def git_commit() -> str:
    out = subprocess.run(
        ["git", "describe", "--always", "--dirty"], capture_output=True, text=True, cwd=config.ROOT
    ).stdout.strip()
    return out or "unknown"
```

Create `src/uniswap_lp_economics/analyze.py`:

```python
"""`ulpe analyze`: validated data -> results/ (analysis checks, tables, charts, summary.json)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics import (
    align,
    arbprofit,
    checks,
    config,
    discovery,
    figures,
    flows,
    markouts,
    report,
    validate,
)
from uniswap_lp_economics.build import load_snapshot_meta
from uniswap_lp_economics.data import blocks as bq_blocks
from uniswap_lp_economics.data import transfers
from uniswap_lp_economics.io import read_exact, write_exact
from uniswap_lp_economics.tickbook import TickBook

MARKOUT_NOTE = (
    "Trader side, after the 0.05% swap fee: markout = -(amount_usdc + amount_eth x P_binance(t0 + h)), "
    "t0 = block timestamp, P = last Binance ETHUSDC trade at or before that time. Positive = the swap "
    "won against the pool at that horizon. mean_bp is notional-weighted (sum markout / sum notional); "
    "ci = 95% bootstrap over UTC days (1,000 resamples, seed 42)."
)
FIGURES = {
    "markouts": "1_markouts_by_flow.png",
    "basis": "2_basis_histogram.png",
    "episodes": "3_gap_episodes.png",
    "waterfall": "4_arbitrage_waterfall.png",
    "leadlag": "5_lead_lag.png",
    "bots": "6_bot_gross_vs_kept.png",
}


@dataclass
class Inputs:
    events: pl.DataFrame
    swaps: pl.DataFrame
    trades: pl.DataFrame
    klines: pl.DataFrame
    ticks: pl.DataFrame
    meta: dict[str, int]
    blocks: pl.DataFrame
    other_logs: pl.DataFrame
    transfers: pl.DataFrame
    labels: pl.DataFrame
    bots: list[str]


def _need(path: Path, command: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `ulpe {command}` first")
    return path


def load_inputs(raw: Path, interim: Path, labels_csv: Path) -> Inputs:
    swaps = read_exact(_need(interim / "swaps.parquet", "build"))
    labels = flows.load_labels(labels_csv)
    bots = flows.top_bots(flows.label_swaps(swaps, labels))
    _need(raw / bq_blocks.BLOCKS_FILE, "fetch-blocks")
    if not bq_blocks.bot_tx_logs_current(raw, bots):
        raise FileNotFoundError(
            "top-bot transaction logs are missing or were fetched for other bots; "
            "run `ulpe fetch-blocks`"
        )
    return Inputs(
        events=read_exact(_need(interim / "events.parquet", "build")),
        swaps=swaps,
        trades=pl.read_parquet(_need(interim / "cex_ethusdc.parquet", "build")),
        klines=pl.read_parquet(_need(interim / "cex_ethusdt_1s.parquet", "build")),
        ticks=read_exact(_need(raw / "tickbook_snapshot.parquet", "fetch-snapshot")),
        meta=load_snapshot_meta(raw),
        blocks=pl.read_parquet(raw / bq_blocks.BLOCKS_FILE),
        other_logs=pl.read_parquet(raw / bq_blocks.OTHER_LOGS_FILE),
        transfers=transfers.load_bot_transfers(raw, bots),
        labels=labels,
        bots=bots,
    )


def analysis_input_hashes(raw: Path, interim: Path, labels_csv: Path) -> dict[str, str]:
    files = [
        *sorted(interim.glob("*.parquet")),
        raw / "tickbook_snapshot.parquet",
        raw / "snapshot_meta.json",
        raw / bq_blocks.BLOCKS_FILE,
        raw / bq_blocks.OTHER_LOGS_FILE,
        *sorted((raw / transfers.TRANSFERS_DIR).glob("*.parquet")),
    ]
    hashes = {p.relative_to(raw.parent).as_posix(): validate.file_hash(p) for p in files}
    hashes[f"labels/{labels_csv.name}"] = validate.file_hash(labels_csv)
    return hashes


def build_aligned(
    labelled: pl.DataFrame, ref: pl.DataFrame, end_us: int, inp: Inputs, shift_s: float = 0.0
) -> pl.DataFrame:
    """One row per swap: reference prices, markouts and costs (plan Ruling 5)."""
    a = align.add_reference_prices(labelled, ref, end_us, shift_s=shift_s)
    a = markouts.add_markouts(a)
    scope = arbprofit.tx_scope(inp.other_logs)
    return arbprofit.add_costs(a, inp.blocks, inp.transfers, scope, inp.bots)


def analyze(
    inp: Inputs,
    results_dir: Path,
    processed_dir: Path,
    provenance: dict[str, Any],
    end_us: int | None = None,
) -> str:
    end_us = align.window_end_us() if end_us is None else end_us
    labelled = flows.label_swaps(inp.swaps, inp.labels)
    ref = align.reference_table(inp.trades)
    aligned = build_aligned(labelled, ref, end_us, inp)
    fee_protocol = int(inp.meta["fee_protocol"])
    series = discovery.build_block_series(
        inp.events,
        TickBook.from_snapshot(inp.ticks, inp.meta),
        fee_protocol,
        inp.blocks,
        ref,
        end_us,
    )
    results = [
        checks.check_a1(inp.events, TickBook.from_snapshot(inp.ticks, inp.meta), fee_protocol),
        checks.check_a2(series, inp.blocks, inp.events, int(inp.meta["block"]) + 1),
        checks.check_a3(aligned),
        checks.check_a4(aligned, int(ref["ts_us"].min()), end_us),  # type: ignore[arg-type]
        checks.check_a5(labelled),
        checks.check_a6(inp.transfers, aligned, inp.blocks),
    ]
    status = checks.write_checks(results, results_dir, provenance)
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.name}: {r.summary}")
    if status != "PASS":
        return status
    processed_dir.mkdir(parents=True, exist_ok=True)
    write_exact(aligned, processed_dir / "aligned.parquet")
    write_exact(series, processed_dir / "blocks_state.parquet")
    _write_results(inp, labelled, aligned, series, ref, end_us, results_dir, provenance)
    return status


def _write_results(
    inp: Inputs,
    labelled: pl.DataFrame,
    aligned: pl.DataFrame,
    series: pl.DataFrame,
    ref: pl.DataFrame,
    end_us: int,
    out: Path,
    provenance: dict[str, Any],
) -> None:
    figs = out / "figures"

    # Markouts (spec 5) and robustness.
    tables = markouts.markout_tables(aligned)
    report.write_table(tables, out, "markouts", "Trader markouts vs Binance", [MARKOUT_NOTE])
    by_label = tables.filter(pl.col("grouping") == "flow_label")
    variants = {
        "primary": aligned,
        "ethusdt_reference": build_aligned(
            labelled, align.kline_reference_table(inp.klines), end_us, inp
        ),
        "t0_minus_2s": build_aligned(labelled, ref, end_us, inp, shift_s=-2.0),
        "exclude_stale_over_5s": markouts.exclude_stale(aligned),
    }
    robustness = pl.concat(
        [
            markouts.markout_table(df, ["flow_label"]).with_columns(variant=pl.lit(name))
            for name, df in variants.items()
        ]
    ).select("variant", pl.exclude("variant"))
    report.write_table(
        robustness, out, "markouts_robustness", "Markout robustness by flow label", [MARKOUT_NOTE]
    )
    figures.markout_curves(by_label, figs / FIGURES["markouts"])

    # Labels.
    coverage = flows.label_coverage(labelled)
    report.write_markdown(
        out,
        "labels_coverage",
        "Flow label coverage",
        [
            ("Notional by label", coverage),
            ("Top unlabelled pool callers (sender)", flows.top_unlabelled(labelled, "sender")),
            ("Top unlabelled transaction targets (to_address)", flows.top_unlabelled(labelled, "to_address")),
        ],
    )

    # Price discovery (spec 6).
    basis = discovery.basis_stats(series)
    report.write_markdown(out, "basis", "Pool vs Binance basis", [("", report.metrics_table(basis))])
    figures.basis_histogram(series, figs / FIGURES["basis"], discovery.FEE_BAND_BP)
    episodes = {
        k: discovery.find_episodes(series, labelled, k) for k in discovery.EPISODE_THRESHOLDS_BP
    }
    summaries = {k: discovery.episode_summary(e) for k, e in episodes.items()}
    all_episodes = pl.concat(
        [e.with_columns(threshold_bp=pl.lit(k)) for k, e in episodes.items()], how="vertical_relaxed"
    )
    all_episodes.write_csv(out / "episodes.csv")
    report.write_markdown(
        out,
        "episodes",
        "Gap episodes and who closes them",
        [(f"|basis| > {k:g} bp", s) for k, s in summaries.items()],
    )
    primary_k = discovery.EPISODE_THRESHOLDS_BP[0]
    figures.episode_chart(episodes[primary_k], summaries[primary_k], figs / FIGURES["episodes"])
    xc = discovery.cross_correlation(series)
    ar1 = discovery.ar1_half_life(series)
    report.write_markdown(
        out,
        "leadlag",
        "Lead-lag",
        [("Cross-correlation (positive lag = Binance first)", xc), ("AR(1) basis", report.metrics_table(ar1))],
        digits=4,
    )
    figures.cross_correlation_chart(xc, figs / FIGURES["leadlag"])

    # Available vs captured vs kept (spec 5.5, 6.5).
    w = arbprofit.waterfall(series, aligned)
    ratios = {
        "captured_over_available": (
            w["captured_searchers_usd"] / w["available_usd"] if w["available_usd"] else None
        ),
        "kept_over_top_bot_gross": (
            w["kept_usd"] / w["top_bot_single_pool_gross_usd"]
            if w["top_bot_single_pool_gross_usd"]
            else None
        ),
    }
    daily = discovery.available_vs_captured(series, aligned)
    report.write_markdown(
        out,
        "arbitrage",
        "Arbitrage: available, captured, kept",
        [("Totals", report.metrics_table({**w, **ratios})), ("By day", daily)],
        notes=[report.LIMITATION_TEXT],
    )
    figures.waterfall_chart(w, figs / FIGURES["waterfall"])
    bot_profit = arbprofit.bot_profit_table(aligned)
    report.write_table(
        bot_profit, out, "bot_profit", "Top bots: gross vs kept", [report.LIMITATION_TEXT]
    )
    figures.bot_profit_chart(bot_profit, figs / FIGURES["bots"])

    total = bot_profit.filter(pl.col("sender") == "TOTAL").to_dicts()
    report.write_summary(
        {
            **provenance,
            "window": f"[{config.WINDOW_START}, {config.WINDOW_END})",
            "swaps": aligned.height,
            "notional_usd": float(aligned["notional_usd"].sum()),
            "top_bots": inp.bots,
            "markouts_all": tables.filter(pl.col("grouping") == "all").to_dicts(),
            "markouts_by_label": by_label.to_dicts(),
            "basis": basis,
            "episodes": {f"{k:g}bp": s.to_dicts() for k, s in summaries.items()},
            "episode_counts": {f"{k:g}bp": e.height for k, e in episodes.items()},
            "lead_lag": {"cross_correlation": xc.to_dicts(), "ar1": ar1},
            "arbitrage": {**w, **ratios},
            "bot_profit_total": total[0] if total else None,
            "label_coverage": coverage.to_dicts(),
            "limitation": report.LIMITATION_TEXT,
        },
        out,
    )


def run_analysis() -> str:
    validate.require_validated()
    inp = load_inputs(config.RAW_DIR, config.INTERIM_DIR, config.LABELS_CSV)
    provenance = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": validate.git_commit(),
        "input_sha256_16": analysis_input_hashes(
            config.RAW_DIR, config.INTERIM_DIR, config.LABELS_CSV
        ),
    }
    return analyze(inp, config.RESULTS_DIR, config.PROCESSED_DIR, provenance)
```

- [ ] **Step 4: Wire the CLI**

In `src/uniswap_lp_economics/cli.py`, import `from uniswap_lp_economics import analyze as analysis`,
register `sub.add_parser("analyze", help="run checks A1-A6 and write results/ (tables, charts, summary)")`
after `validate`, and dispatch:

```python
    elif args.command == "analyze":
        try:
            status = analysis.run_analysis()
        except (FileNotFoundError, RuntimeError) as e:
            raise SystemExit(str(e)) from e
        raise SystemExit(0 if status == "PASS" else 1)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_analyze.py -q`
Expected: PASS. If a check fails, the assertion message prints `analysis_checks.md`; fix the cause,
not the check.

- [ ] **Step 6: Format, lint, type-check, full tests, commit, push**

```bash
uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q
git add src/uniswap_lp_economics/analyze.py src/uniswap_lp_economics/config.py src/uniswap_lp_economics/validate.py src/uniswap_lp_economics/cli.py tests/test_analyze.py
git commit -m "Add ulpe analyze: checks, results tables, charts and summary"
git push
```

---

### Task 16: Run on the real data and review the labels (controller task; network)

This task fetches real data (BigQuery, Alchemy) and judges the results. It is run by the controller,
not dispatched blind. Every command runs from the repo root with `DATA_DIR` pointing at the real data.

- [ ] **Step 1: Confirm the inputs are still the validated ones**

Run: `uv run python -c "from uniswap_lp_economics.validate import require_validated; require_validated(); print('ok')"`
Expected: `ok`.

- [ ] **Step 2: Dry-run the BigQuery fetches**

Run: `uv run ulpe fetch-blocks --dry-run`
Expected: the number of top bots (at most 25) and two "scans N GB" lines, each under 150 GB (the
per-query cap). If the other-logs query is over the cap, change `fetch_bot_tx_logs` to run one query
per `bigquery.month_windows` window and concatenate (ledger the ruling), then dry-run again.

- [ ] **Step 3: Fetch**

Run: `uv run ulpe fetch-blocks` then `uv run ulpe fetch-transfers`
Expected: `blocks.parquet` with one row per block from 25,433,939 to the window's last block;
`bot_tx_other_logs.parquet`; one transfer file per top bot. Re-running either command skips what is
already there.

- [ ] **Step 4: Analyse**

Run: `uv run ulpe analyze`
Expected: six PASS lines and exit code 0. A1 must report 0 swaps outside tolerance. If any gated
check fails, use superpowers:systematic-debugging; never loosen a tolerance to make it pass.

- [ ] **Step 5: Review the labels**

Read `results/labels_coverage.md`. For every unlabelled `to_address` or `sender` with at least 1% of
total notional, look up its public name tag on Etherscan (WebFetch
`https://etherscan.io/address/<address>`). Add to `labels/addresses.csv`, with that page as
`source_url`, only public routers, aggregators or settlement contracts. Leave private bots and unnamed
contracts unlabelled. If rows were added, rerun `uv run pytest tests/test_flows.py -q`,
`uv run ulpe fetch-blocks`, `uv run ulpe fetch-transfers` (the top-bot set can change) and
`uv run ulpe analyze`.

- [ ] **Step 6: Sanity-review the results**

Read `results/summary.json` and the markdown tables. Expected shape:
- `basis.quantiles_bp["0.5"]` within a few bp of 0;
- searchers' 0s markout positive;
- `arbitrage.available_usd` ≥ `arbitrage.captured_searchers_usd`;
- `kept_usd` < `top_bot_single_pool_gross_usd`;
- the cross-correlation peak at a positive lag.

A result that breaks one of these is a finding to investigate (data or logic), not a number to
adjust. Record what you checked and what you found in the ledger.

- [ ] **Step 7: Commit the results**

```bash
git add results labels/addresses.csv
git commit -m "Add sub-project 2 results: markouts, price discovery, arbitrage net of costs"
git push
```

---

### Task 17: Methodology and README

**Files:**
- Create: `docs/methodology.md`
- Modify: `README.md`

All numbers come from `results/summary.json` and the `results/*.md` tables produced in Task 16; quote
them with the same rounding as the tables. No number may appear that is not in `results/`.

- [ ] **Step 1: Write `docs/methodology.md`**

Sections, in this order, each stating the definition and formula from the spec:
1. Data and validation (link to `data_validation/validation_report.md` and `results/analysis_checks.md`).
2. Reference price and time zero (spec 5.1; Ruling 6).
3. Markouts: the trader, LP and protocol formulas (spec 5.2), the `notional_usd` definition and its
   ≤ 0.05% bp distortion (spec section 2, item 3), aggregation and the day bootstrap (5.3), robustness
   variants.
4. Flow labels: the CSV, the four rules in order, top bots (5.4).
5. Costs and builder payments: the three cost formulas, single- vs multi-pool, allocation by notional
   (5.5), then `report.LIMITATION_TEXT` verbatim.
6. Block series, basis, episodes and closers, lead-lag and AR(1) half-life (6.1–6.4).
7. Available arbitrage: target prices `P_cex·(1−f)·(1−c)` and `P_cex·(1+c)/(1−f)` (Ruling 1), exact
   V3 swap simulation (Ruling 2), assumptions (no gas, unlimited Binance depth, Binance fee 0 or 1 bp).
8. Checks A1–A6 and what each proves.

- [ ] **Step 2: Update `README.md`**

- Status line: sub-projects 1 (data) and 2 (price discovery and markouts) are complete; LP P&L is next.
- **TL;DR:** the question; three findings with numbers, each with its main caveat, chosen from:
  markouts by flow (`markouts_by_label`); basis and gap half-life (`basis`, `lead_lag.ar1`); available
  → captured → kept and the builder share (`arbitrage`, `bot_profit_total`). Below it, the headline
  chart `results/figures/1_markouts_by_flow.png`.
- **Method:** five lines, linking `docs/methodology.md`.
- **Results:** charts 1–6, each with one sentence saying what it shows, and the key rows of
  `results/markouts.md` (flow-label grouping) and `results/bot_profit.md` (TOTAL row).
- **Limitations:** `report.LIMITATION_TEXT` verbatim, then: reference = last Binance trade (no order
  book); t0 = block timestamp; available arbitrage ignores gas, Binance fees beyond the 1 bp sensitivity,
  and Binance depth; labels are a curated list plus heuristics; multi-pool bot transactions get no
  cost breakdown.
- **Reproduce:** add `uv run ulpe fetch-blocks`, `uv run ulpe fetch-transfers`, `uv run ulpe analyze`
  after the existing steps.
- **Repo map:** add `labels/`, `results/`, `docs/methodology.md` and the new modules (`replay`,
  `v3swap`, `flows`, `align`, `markouts`, `arbprofit`, `discovery`, `checks`, `report`, `figures`,
  `analyze`, `data/blocks`, `data/transfers`), one line each.

- [ ] **Step 3: Check every number**

For each number in the README TL;DR and Results, find it in `results/` and confirm it matches. List
any you could not find and remove them.

- [ ] **Step 4: Format check, commit, push**

```bash
uv run ruff format --check . && uv run pytest -q
git add docs/methodology.md README.md
git commit -m "Document sub-project 2 method and findings"
git push
```
