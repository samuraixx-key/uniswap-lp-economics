# Sub-project 2 — Price discovery and markouts: design

Date: 2026-10-13 · Status: approved in conversation, awaiting written-spec review

## 1. Context and intent

**Project goal (user):** learn DeFi market microstructure and land a DeFi trading/quant job.
`uniswap-lp-economics` is the flagship portfolio repo. Sub-project 1 (data foundation) is merged and
validated: all checks C1–C6 pass on the window `[2026-07-01, 2026-10-01)` UTC.

**This sub-project answers two questions:**
1. **Price discovery:** how far does the pool price drift from Binance, how long does a gap last, and
   who closes it?
2. **Markouts by flow type:** measured against Binance's later price, which kinds of flow win against
   the pool and which lose to it, and how much of the arbitrageurs' gross edge do they actually keep
   after gas and payments to block builders?

**Guiding rule (roadmap):** measure what actually happened, separate "existed" from "capturable", state
limitations up front. Here that becomes the chain
**available arbitrage → captured (gross) → kept (net of gas and builder payments)**.

**Success criteria:**
- `uv run ulpe analyze` regenerates every table, chart and number in `results/` from validated data.
- Analysis checks A1–A6 (section 7) pass, and the gated ones are enforced.
- The README gets its first real TL;DR: three findings with numbers and a caveat each, plus the headline
  chart, all quoted from `results/summary.json`.
- CI passes offline.

**Decisions made in brainstorming:**
- Flow labels: a **curated address CSV with a source per address**, then heuristics (option B).
- Arbitrage profit: gross markouts minus gas minus **builder payments for the top bot contracts**, using
  Alchemy `alchemy_getAssetTransfers` (option C). The detection limitation must be stated wherever the
  method is described (section 9).
- Output form: pipeline-generated only. `ulpe analyze` writes CSV, markdown and PNG into a committed
  `results/` folder; no notebooks (option A).
- Structure: **swap-centric** (one aligned row per swap, exact as-of joins) with a derived **per-block
  series** for price discovery (approach 1).

**Out of scope:** LP P&L, LVR and fee-growth/position accounting (sub-project 3), counterfactual
strategies (sub-project 4), making the repo public.

## 2. Carry-over items from sub-project 1 (first tasks)

1. **Hash-drift check.** `require_validated()` currently checks only `status == PASS`. It must also
   recompute the SHA-256 prefix of each `interim/*` file listed in `validation_report.json` and refuse
   to run if any differs, naming the file.
2. **Public replay helper.** New `replay.py` (section 4). `validate.replay` is refactored onto it so the
   replay logic exists once; C1–C3 results must be unchanged.
3. **`notional_usd` definition.** Documented as `|amount_usdc|`: it includes the 0.05% fee on USDC-in
   swaps and excludes it on USDC-out swaps. Used as the bp denominator, this asymmetry changes a
   markout by at most 0.05% of its own value (0.0025 bp on a 5 bp markout). Stated in
   `docs/methodology.md`; the column is not changed.
4. Fee-growth and position accounting remain deferred to sub-project 3.

## 3. Data layout

```
data/raw/                      (git-ignored)
  blocks.parquet               NEW  BigQuery `blocks`: number, timestamp, miner, base_fee_per_gas
  bot_tx_other_logs.parquet    NEW  BigQuery `logs`: per top-bot tx, count of logs from addresses outside the allowed set
  bot_transfers.parquet        NEW  Alchemy internal ETH transfers from top bot contracts
data/processed/                NEW  (git-ignored; rebuilt by `ulpe analyze`)
  aligned.parquet              one row per swap (section 5)
  blocks_state.parquet         one row per block in the window (section 6)
labels/addresses.csv           NEW  (committed) curated address labels
results/                       NEW  (committed)
  summary.json                 every headline number + git commit + input hashes
  analysis_checks.json / .md   checks A1–A6
  markouts.csv / .md, markouts_robustness.md, labels_coverage.md,
  basis.md, episodes.csv / .md, leadlag.md, arbitrage.md, bot_profit.csv / .md
  figures/*.png
docs/methodology.md            NEW  (committed) every definition in sections 5–7
```

The window covers blocks 25,433,939–26,093,736 (659,798 blocks). `blocks.parquet` must contain every
one of them.

## 4. Components

| Module | Responsibility |
|---|---|
| `replay.py` | Public replay. From the snapshot tick book and `events.parquet` in `(block_number, log_index)` order, yields pool state (`sqrt_price_x96`, `tick`, `liquidity`, plus read access to the `TickBook`) after every event, and a per-block iterator giving state at each block's start and end. `validate.py` uses it. |
| `v3swap.py` | Float swap math across ticks over a `TickBook` state: `simulate_exact_input(state, amount_in, zero_for_one, fee_pips)` returning amount out and final sqrt price, and `arb_to_price(state, target_price, fee_pips)` returning the amounts traded and the profit at a reference price. Uses the standard V3 per-range formulas (`Δx = L·(1/√Pa − 1/√Pb)`, `Δy = L·(√Pb − √Pa)`), fee taken from the input. |
| `labels/addresses.csv` + `flows.py` | Loads and validates the CSV, labels each swap (section 5.4), selects the top bot contracts. |
| `data/blocks.py` | Guarded BigQuery fetches (dry run, byte cap, atomic write, same style as `data/bigquery.py`): blocks in the window; and per top-bot transaction, the count of logs emitted by any address other than our pool, USDC, WETH and the transaction's `to_address` (the bot contract itself). |
| `data/transfers.py` | Alchemy `alchemy_getAssetTransfers` for `category=["internal"]`, `fromAddress` = each top bot, the window's block range, paginated with `pageKey` (`maxCount` 1000), through the existing `RpcClient` (retries, no URL in errors). Cached; reruns skip contracts already fetched. |
| `align.py` | Builds `aligned.parquet` (section 5). |
| `markouts.py` | Markout aggregation, day-block bootstrap, robustness tables. |
| `discovery.py` | Builds `blocks_state.parquet`; basis distribution, episodes, lead-lag, available vs captured (section 6). |
| `arbprofit.py` | Gross → gas (burned / priority) → coinbase payments → kept, per top bot (section 5.5). |
| `checks.py` | Analysis checks A1–A6 and their report (section 7). |
| `figures.py`, `report.py` | Charts (matplotlib, Agg backend) and tables in `results/`; `summary.json`. |

**CLI** (added to `cli.py`): `fetch-blocks` (blocks plus other-pool swap counts; needs the top-bot
list, so it runs labelling first), `fetch-transfers`, `analyze`. `analyze` calls `require_validated()`
first and refuses to run if the raw inputs it needs are missing.

## 5. Markouts

### 5.1 Reference price and time zero
- **Reference:** price of the last Binance ETHUSDC trade at or before time *t* (`P_cex(t)`). No order
  book data exists for the window, so the reference is built from trades; bid-ask bounce on ETHUSDC is
  under 0.1 bp. Each lookup also stores the reference's age in seconds.
- **Time zero:** `t0 = block_timestamp`.
- **Horizons:** 0s, 12s, 60s, 300s, 3600s. A horizon whose time is past the end of the Binance data has
  a null reference and is excluded from that horizon's statistics (counted in A4).

### 5.2 Definitions (trader's side, USD)
`amount_usdc` and `amount_eth` are the pool's amounts (positive = into the pool), already including the
swap fee:
```
trader_markout_usd(h) = −( amount_usdc + amount_eth × P_cex(t0 + h) )
trader_markout_bp(h)  = trader_markout_usd(h) / notional_usd × 10⁴
protocol_fee_usd      = fee_usd × fee_protocol_share
lp_markout_usd(h)     = −trader_markout_usd(h) − protocol_fee_usd
```
Positive trader markout = the swap won against the pool at that horizon, after the swap fee.

### 5.3 Aggregation
- Groups: flow label × size bucket × horizon, plus each dimension alone and an all-swaps row.
- Size buckets on `notional_usd`: `<1k`, `1k–10k`, `10k–100k`, `≥100k`.
- Per group: swap count, total notional, total trader markout USD, notional-weighted mean markout bp,
  median markout bp, and a 95% confidence interval for the weighted mean from a **bootstrap over UTC
  days** (1,000 resamples, fixed seed 42).
- **Robustness tables** (`markouts_robustness.md`), each re-running the main table:
  1. ETHUSDT 1s close as the reference (last close at or before *t*);
  2. `t0 − 2s`;
  3. excluding swaps whose `t0` reference is older than 5s.

### 5.4 Flow labels
`labels/addresses.csv` columns: `address, name, category, source_url, notes`. Allowed categories:
`uniswap_router`, `aggregator`, `intent_settlement`. Every address is verified against official
deployment docs or Etherscan's public label page while building the list, and `source_url` points to
that page.

Labelling, first match wins:
1. `to_address` is in the CSV → its category.
2. `sender` is in the CSV → its category.
3. `sender == to_address` → `searcher`.
4. Otherwise → `other_contract`.

Extra fields: `top_of_block` (`transaction_index ≤ 2`) and the size bucket.

**Top bot contracts:** `searcher` senders ranked by notional; the smallest prefix covering ≥ 90% of
`searcher` notional, capped at 25.

`labels_coverage.md`: notional share per label, and the 30 unlabelled (`other_contract`) `sender` and
`to_address` values with the most notional.

### 5.5 Costs and builder payments
Per transaction (USD at `P_cex(t0)`):
```
gas_burned_usd   = gas_used × base_fee_per_gas            / 10¹⁸ × P_cex(t0)
priority_fee_usd = gas_used × (effective_gas_price − base_fee_per_gas) / 10¹⁸ × P_cex(t0)
coinbase_usd     = Σ internal transfers from the bot contract to the block's miner in this tx / 10¹⁸ × P_cex(t0)
```
`base_fee_per_gas` and `miner` come from `blocks.parquet`. Costs of a transaction with several swaps in
our pool are split across them by notional.

**Single-pool vs multi-pool:** a top-bot transaction is `single_pool` (classic CEX-DEX
arbitrage) when every log it emits comes from our pool, USDC, WETH or the bot contract itself. These get the full breakdown: gross (0s markout) → minus gas
burned → minus priority fee → minus coinbase payment → kept. `multi_pool` transactions are reported
separately, gross only, because their costs cannot be split per pool. Swaps outside the top bots get
gas costs only.

`bot_profit.csv`: per top bot and in total, swaps, notional, the breakdown above, and the share of its
transactions carrying a coinbase payment. Builder income = priority fee + coinbase payment.

## 6. Price discovery

### 6.1 Block series (`blocks_state.parquet`)
One row per block in the window: block number and timestamp; pool `sqrt_price_x96`, tick and liquidity
at block start (state after the previous block's last event, carried through blocks without pool
events); pool price at block end; `P_cex` at the block timestamp and its age; swap count in the block.
```
basis_bp = ln(P_pool_start / P_cex(block_timestamp)) × 10⁴
```

### 6.2 Basis distribution
Quantiles (1, 5, 25, 50, 75, 95, 99%) of `basis_bp` and `|basis_bp|`, histogram, and share of blocks
with `|basis_bp| > 5` (the fee band: below it an arbitrage loses money before gas).

### 6.3 Gap episodes
- An episode is a maximal run of consecutive blocks with `|basis_bp| > k`, for k = 5 (primary) and 10.
- Per episode: start block, duration in blocks and seconds, peak `|basis_bp|`, and how it ended:
  - The episode's last block *e* is the last one whose start basis is outside the band; block *e+1*
    starts inside it.
  - `swap`: block *e* contains at least one swap that moved the pool's log price toward
    `P_cex(timestamp of e)`; the closer is the flow label of the swap that moved it furthest;
  - `cex`: block *e* has no such swap, so Binance moved back to the pool;
  - `open`: the episode runs to the end of the window.
- Outputs: episodes per closer type (count share and gap-weighted time share, where weight =
  Σ |basis_bp| × block seconds), and a survival curve of durations.

### 6.4 Lead-lag
Per-block log returns of pool (block start to next block start) and Binance (between consecutive block
timestamps); cross-correlation at lags −5…+5 blocks. AR(1) fit `basis_{b+1} = φ·basis_b + ε` by OLS;
half-life `= ln(0.5) / ln(φ)` blocks, and in seconds using the median block interval.

### 6.5 Available vs captured arbitrage
- **Available** at each block start: `v3swap.arb_to_price` moves the pool to the price where its
  marginal price after the fee equals `P_cex`, i.e. `P_cex × (1 + fee)` if the pool is cheap and
  `P_cex / (1 + fee)` if it is expensive, crossing ticks as needed. Profit = USD value at `P_cex` of
  what the arbitrageur receives minus what they pay. Assumes no gas, unlimited Binance liquidity and no
  Binance trading fee. Sensitivity: the same with a 1 bp Binance fee (target band widened by 1 bp).
- **Captured:** sum of 0s trader markouts of `searcher` swaps in the same block.
- Outputs (`arbitrage.md`): window totals, daily series, and the ratios captured/available and
  kept/captured (kept from section 5.5, single-pool top-bot transactions).

## 7. Analysis checks

Written to `results/analysis_checks.{json,md}` before any result; a failed gated check stops `analyze`.

| Check | Verifies | Gate |
|---|---|---|
| A1 | `v3swap.simulate_exact_input` reproduces every historical swap: from the replayed state before the swap, with the swap's actual input amount and direction, the simulated output amount and final sqrt price match the event's | max relative error < 1e-9 on both |
| A2 | Block series complete: every block 25,433,939–26,093,736 present once; each block's start state equals the previous block's end state | exact |
| A3 | Per swap and horizon: trader markout + LP markout + protocol fee = 0 | abs < 1e-6 USD |
| A4 | Reference coverage: per horizon, swaps without a reference; swaps with reference age > 5s | gated: a reference at horizon h may be null only if `t0 + h` is after the last Binance trade (or `t0` before the first); any other null fails; counts reported |
| A5 | Label coverage: notional share of `other_contract`; top unlabelled addresses | reported |
| A6 | Builder payments: matched transfers, share of top-bot txs with a coinbase payment, count of internal transfers from top bots to non-miners | reported |

`summary.json` carries the git commit (`git describe --always --dirty`) and the SHA-256 prefix of every
input file, as the validation report does.

## 8. Charts (`results/figures/`)
1. **Headline:** trader markout curves by flow label (0s → 1h, bp, notional-weighted) with bootstrap
   bands.
2. Basis histogram with the ±5 bp fee band.
3. Episode duration survival curve, plus closer shares.
4. Waterfall: available → captured → minus gas burned → minus priority fee → minus coinbase → kept.
5. Pool vs Binance cross-correlation by lag.
6. Gross vs net per top bot.

## 9. Documentation
- `docs/methodology.md`: every definition in sections 5–7, with the formulas.
- README:
  - TL;DR: three findings with numbers and one caveat each, plus chart 1.
  - Method (short, links to `docs/methodology.md`), Results (charts 1–6 and key tables).
  - Limitations.
  - Reproduce adds `ulpe fetch-blocks`, `ulpe fetch-transfers`, `ulpe analyze`.
  - Repo map.
- **Required limitation text** (README Limitations, `docs/methodology.md`, and next to the net numbers in
  `arbitrage.md` and `bot_profit.md`):
  > Builder payments are detected only as direct ETH transfers from the bot contract to the block's fee
  > recipient within the same transaction. Payments routed elsewhere (another contract, a separate
  > transaction in the bundle, off-chain agreements) are missed, so the reported net profit is an
  > **upper bound** on what the bots keep. Binance-side trading fees, inventory and hedging costs are not
  > observed.
- Other limitations listed in the README: last-trade reference (no order book); `t0` = block timestamp;
  available arbitrage ignores gas, Binance fees and Binance depth; labels come from a curated list plus
  heuristics; multi-pool transactions get no cost breakdown.

## 10. Testing
- Unit tests on small synthetic inputs, one file per module:
  - as-of alignment and horizons, including stale and missing references;
  - markout sign and USD/bp maths against hand-worked swaps, and the A3 identity;
  - each labelling rule and its precedence; CSV validation (unique, lowercase hex, allowed category,
    non-empty source);
  - top-bot selection (90% coverage, cap 25);
  - episode detection: start, end, `swap` vs `cex` closer, `open`, both thresholds;
  - AR(1) half-life on a known synthetic series; cross-correlation lag sign;
  - `v3swap` within one range and across ticks, against hand-computed values; `arb_to_price` leaves the
    pool at the target price;
  - cost split across several swaps in one transaction; single vs multi-pool classification;
  - `require_validated` hash drift.
- Real-data fixture: the existing 400-event fixture drives `replay` and A1 on its swaps.
- Fetchers offline with fake transports (Alchemy pagination and caching, BigQuery query text and dry-run
  cap); real calls marked `live`.
- CI unchanged: ruff, ruff format, mypy --strict, pytest (offline).

## 11. Risks
| Risk | Mitigation |
|---|---|
| Alchemy free tier rejects or throttles `alchemy_getAssetTransfers` for internal transfers over long ranges | Paginate and split the block range per month; `RpcClient` retries; cache per contract; a live smoke test before the full fetch |
| BigQuery `logs` scan for other-pool swaps exceeds the sandbox budget | Dry run first; byte cap; filter by partition and by the top-bot tx hashes via the `transactions` join on `to_address` |
| Python replay plus `v3swap` over 660k blocks and 534k swaps is slow | Measured on the fixture first; per-block arbitrage uses only ticks between the current and target price; acceptable if the full run stays under ~30 min |
| Curated labels miss important routers | `labels_coverage.md` lists the top unlabelled addresses; the list is extended before results are written up |
| Builder payments understated | Stated as an upper bound on net profit (section 9) |
