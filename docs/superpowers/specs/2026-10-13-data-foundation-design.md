# Sub-project 1 — Data foundation: design

Date: 2026-10-13 · Status: approved in conversation, awaiting written-spec review

## 1. Context and intent

**Project goal (user):** learn DeFi market microstructure and land a DeFi trading/quant job.
`uniswap-lp-economics` is the flagship portfolio repo: a study of the Uniswap V3 USDC/WETH 0.05% pool
on Ethereum mainnet against Binance, with a findings-first README and honest limitations.

**Decomposition (agreed):**
1. **Data foundation (this spec):** decoded events, tick book, CEX prices, and validation.
2. Price discovery and markouts.
3. LP profit and loss: fees vs LVR.
4. Counterfactual LP strategies.
5. Report and README.

Each later sub-project gets its own spec → plan → implementation cycle and reads only this
sub-project's validated outputs.

**Success criteria for sub-project 1:**
- One command (`uv run ulpe all`) rebuilds every intermediate table from raw downloads.
- The validation report says PASS on all checks C1–C6 (section 5) and is committed.
- Its headline numbers are fit to quote in the README, e.g. "N/N swaps consistent; 500/500 on-chain
  samples exact".
- CI passes offline, including a real-data integration test.

**Fixed choices:**
- Pool `0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`: token0 USDC (6 dp), token1 WETH (18 dp), fee
  500 pips, tick spacing 10.
- Study window: **[2026-07-01, 2026-10-01) UTC**. Pool logs for it are already downloaded
  (556,664 logs, blocks 25,433,939–26,093,736).
- Liquidity depth: **full tick book**, built as a snapshot at the start plus a replay of mints and burns
  (approach A). Replaying from the pool's creation is infeasible: about 3 TB on BigQuery, or about 1M
  free-tier RPC calls.
- CEX reference: **Binance spot ETHUSDC aggTrades** (primary, ms timestamps) and **ETHUSDT 1s klines**
  (robustness). Binance stopped publishing bookTicker (bid/ask) after 2024-03-30, so the reference is
  built from trades.

**Out of scope here:** flow classification (sub-project 2), LP P&L and LVR (sub-project 3), and swap
simulation under alternative parameters (sub-project 4).

## 2. Data layout

```
data/raw/          (downloaded once, never edited; git-ignored)
  pool_logs_<start>_<end>.parquet       BigQuery, one per month (done)
  tickbook_snapshot.parquet             RPC: every initialized tick at SNAPSHOT_BLOCK
  snapshot_meta.json                    SNAPSHOT_BLOCK, slot0 (incl. feeProtocol), liquidity()
  onchain_samples.parquet               RPC: state at random validation blocks
  binance/ETHUSDC-aggTrades-YYYY-MM.zip (+ .CHECKSUM)
  binance/ETHUSDT-1s-YYYY-MM.zip        (+ .CHECKSUM)
data/interim/      (rebuilt by `ulpe build`; git-ignored)
  events.parquet                        one row per decoded pool event
  swaps.parquet                         swaps with derived fields
  cex_ethusdc.parquet                   trades: ts_ms, price, qty, is_buyer_maker
  cex_ethusdt_1s.parquet                1-second close prices
data/validation/   (committed)
  validation_report.json / .md
tests/fixtures/    (committed, small)
  real event slice + matching partial tick book
```

**SNAPSHOT_BLOCK** is the last block with a timestamp before 2026-07-01 00:00:00 UTC. It is found by
binary search on `eth_getBlockByNumber` timestamps and recorded in `snapshot_meta.json`.

**events.parquet columns:**
- Ordering and source: `block_number`, `block_timestamp`, `transaction_index`, `log_index`, `tx_hash`,
  `from_address`, `to_address`, gas fields.
- Event fields: `event` (swap/mint/burn/collect/flash/set_fee_protocol/other), then the decoded fields
  as **Int128**: `amount0`, `amount1`, `sqrt_price_x96`, `liquidity`, `amount`, `tick`, `tick_lower`,
  `tick_upper`, `owner`, `sender`, `recipient`, `paid0`, `paid1`, fee-protocol fields.
- Readable float columns: `amount_usdc`, `amount_eth`, `price_usd` (USD per ETH, swaps only).

**swaps.parquet** adds, per swap:
- `direction`: `buy_eth` or `sell_eth`.
- `notional_usd`.
- `fee_token`, `fee_amount_raw`, `fee_usd`. The fee is charged on the input amount, and the event's
  input amount `a` already includes it. We define `fee_amount_raw = ceil(a * 500 / 1e6)`. This is an
  approximation of V3 `SwapMath`, which rounds once per tick-crossing step, so it is accurate to
  within a few base units per crossed tick. That is negligible against 0.05% of any real swap.
  Exact per-step fees would need full swap simulation, which is sub-project 4.
- `pre_sqrt_price_x96` and `pre_price_usd`: the pool state just before the swap (the previous swap's
  post-state, or the snapshot for the first swap).
- `fee_protocol_share`: the protocol-fee fraction in force at that swap. It comes from the snapshot
  `feeProtocol` plus any SetFeeProtocol events, so later sub-projects can split the fee between LPs
  and protocol.

**The tick book is not materialised per event.** `TickBook` is rebuilt by replaying from the
snapshot, which takes seconds for about 14k mints and burns.

## 3. Components

The rule is that pure logic is separated from input/output.

### Pure modules (no network, no files)
- **`v3math.py`** (extend):
  - An exact integer port of Uniswap `TickMath` (`get_sqrt_ratio_at_tick`, `get_tick_at_sqrt_ratio`).
  - The swap fee calculation.
  - The existing float price helpers.
- **`events.py`** (extend):
  - Add `Flash` (fees paid to LPs) and `SetFeeProtocol`.
  - Their topic hashes are verified against real pool logs before use, as was done for the existing
    four.
  - Unknown topics are returned as `other` and counted, never silently dropped.
- **`tickbook.py`** (new). `TickBook` holds:
  - `liquidity_net: dict[int, int]` and `liquidity_gross: dict[int, int]`;
  - `tick` (current tick), `sqrt_price_x96`, `liquidity` (active).

  Methods:
  - `from_snapshot(...)`.
  - `apply_mint(tick_lower, tick_upper, amount)` and `apply_burn(...)`. Both change active liquidity
    when `tick_lower <= tick < tick_upper`.
  - `apply_swap(sqrt_price_x96, tick)`. It moves to the post-swap state and crosses every
    initialized tick between the old and new tick. Moving up past tick t adds `liquidity_net[t]`;
    moving down past t subtracts it.
  - Accessors: `active_liquidity()`, `initialized_ticks()`.

### Input/output modules
- **`rpc.py`**:
  - A JSON-RPC client over httpx: `eth_call(to, data, block)`, `eth_block_number`,
    `get_block_timestamp`.
  - Multicall3 `aggregate3` batching.
  - Retries with exponential backoff on HTTP 429/5xx, up to 5 attempts.
  - ABI encoders and decoders for `slot0()`, `liquidity()`, `tickBitmap(int16)` and `ticks(int24)`.
- **`snapshot.py`**: `read_tick_book(block) -> (ticks DataFrame, meta dict)`. It reads every bitmap
  word covering the valid tick range, collects the initialized ticks, then calls `ticks(t)` for each.
  It is reused for validation samples.
- **`data/bigquery.py`**: exists.
- **`data/binance.py`**: downloads monthly zips to a temporary file, verifies SHA256 against
  `.CHECKSUM`, renames into place, and parses to parquet. Existing valid files are skipped.
- **`build.py`**: raw → interim tables.
- **`validate.py`**: runs C1–C6 and writes the report. Exits non-zero on any failure.
- **`cli.py`** subcommands:
  - `fetch-logs` (exists), `fetch-snapshot`, `fetch-samples`, `fetch-cex`, `build`, `validate`.
  - `all`, which runs them in order and skips completed downloads.

Downstream code reads only `data/interim/*` and the `TickBook`. It calls `require_validated()`, which
raises unless the committed report says PASS.

## 4. Data flow

```
fetch-logs ──► pool_logs ─┐
fetch-snapshot ──► snapshot ─┼─► build ──► events, swaps ──► validate ──► report (PASS/FAIL)
fetch-cex ──► binance zips ──┘          cex tables ──────────┘
fetch-samples ──► onchain_samples ───────────────────────────┘
```

`fetch-samples` picks 500 blocks uniformly at random (seed 42) from the window. At each block it
reads `slot0`, `liquidity()`, and `ticks()` for the 20 initialized ticks nearest the on-chain tick.
"Initialized" is taken from the **on-chain** `tickBitmap` words around the current tick, not from our
replay, so a tick our replay missed still gets sampled. At 5 of those blocks, chosen evenly through
the window, it reads the full book.

## 5. Validation

| # | Check | Pass condition |
|---|---|---|
| C1 | Replay events in order. After each swap, `TickBook.active_liquidity()` equals the event's `liquidity` | 0 mismatches over all swaps |
| C2 | Each swap's `tick` equals `get_tick_at_sqrt_ratio(sqrt_price_x96)` | 0 mismatches |
| C3 | At each sample block, the replayed state after that block's last event equals on-chain `slot0` (sqrtPrice, tick, feeProtocol), `liquidity()` and the sampled `ticks()` (liquidityGross, liquidityNet). At 5 blocks the full set of initialized ticks is compared | Exact match at all 500 |
| C4 | The snapshot's `liquidity_net` sums to 0, and the active liquidity rebuilt from it equals snapshot `liquidity()` | Exact |
| C5 | No duplicate `(block_number, log_index)`. Every log joined to a tx. Timestamps inside the window. Binance checksums OK. Count of `other` events and the longest Binance trade gap are reported | All hold |
| C6 | Median of \|pool price − Binance ETHUSDC price\| at swap timestamps, in bp. A sanity bound only, not a finding | Median < 10 bp |

**C2 rule:** let `t = get_tick_at_sqrt_ratio(sqrt_price_x96)`. C2 passes for a swap if
`tick == t`. It also passes if `tick == t - 1` **and** `sqrt_price_x96 == get_sqrt_ratio_at_tick(t)`.
That second case is a downward swap that stops exactly on a tick boundary, which V3 reports as
`t - 1`. Such cases are counted separately in the report. Anything else is a mismatch.
[Inference] The boundary behaviour follows the V3 core `swap` loop. It is pinned down by a unit test,
and if real data contradicts it, C2 fails loudly rather than being loosened silently.

**The report** gives each check's counts, PASS/FAIL, the first 20 mismatches with their
block/log_index, input file hashes, and the git commit.

**Error handling:**
- Validation failure → non-zero exit.
- Downstream refuses to run without a PASS report.
- RPC responses are cached in the raw parquet files, so reruns cost no calls.
- Downloads are atomic and resumable.
- BigQuery queries are dry-run first and capped at 150 GB.
- State columns are exact integers. Floats appear only in readable or analysis columns.

## 6. Testing

Tests are written first, then the code (TDD).
- **Unit, pure:**
  - `TickMath` against the V3 constants: `MIN_TICK=-887272`, `MAX_TICK=887272`,
    `MIN_SQRT_RATIO=4295128739`, `MAX_SQRT_RATIO=1461446703485210103287273052203988822378723970342`,
    and tick ↔ sqrt round trips.
  - Fee rounding.
  - Event decoding, synthetic and real.
  - `TickBook` scenarios: mint in range and out of range, burn reversing a mint, single and multi-tick
    crossings in both directions, price exactly on `tick_lower`.
- **Unit, input/output without network:**
  - RPC encode/decode against recorded responses.
  - Retry logic via `httpx.MockTransport`.
  - Binance parse of a tiny zip; checksum mismatch raises.
  - BigQuery query builder.
- **Integration, offline, in CI:** a committed fixture of a few hundred consecutive real events plus
  the matching partial tick book. C1 and C2 must pass on it.
- **Live** (`@pytest.mark.live`, skipped by default and in CI): RPC and BigQuery smoke tests, run
  locally with `uv run pytest -m live`.
- **End to end:** a full `ulpe all` producing a PASS report is the definition of done.

## 7. Risks

- **BigQuery completeness:** if logs are missing, C3 catches it, because the state drifts from the
  chain.
- **Free-tier RPC limits:**
  - About 700 bitmap words plus a few thousand `ticks()` calls per full-book read, batched through
    Multicall3.
  - About 6 full-book reads in total (the snapshot plus 5 validation reads).
  - About 500 light samples.
  - [Inference] This stays within Alchemy's free monthly compute units. If not, sampling is reduced
    and the report says so.
- **Protocol fee:** [Unverified] the protocol fee may be switched on for this pool in 2026. It is read
  from chain, not assumed.
