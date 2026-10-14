# Sub-project 3 — LP P&L and where LVR goes: design

Date: 2026-10-14 · Status: approved in conversation, awaiting written-spec review

## 1. Context and intent

**Project goal (user):** learn DeFi market microstructure and land a DeFi trading/quant job.
`uniswap-lp-economics` is the flagship portfolio repo. Sub-project 1 (data foundation) and
sub-project 2 (price discovery and markouts) are merged; checks C1–C6 and A1–A6 pass on the window
`[2026-07-01, 2026-10-01)` UTC, blocks 25,433,939–26,093,737.

**This sub-project answers five questions** (same pool, window and Binance reference):
1. **Do fees cover LVR?** Window and daily totals of LP fees (exact, after the protocol's quarter) vs
   measured LVR, and vs theoretical LVR.
2. **In which volatility conditions?** Fees − LVR by tercile of daily realised volatility.
3. **Which LPs make money?** For every position active in the window: P&L against a rebalancing
   portfolio (fees − LVR) and against holding, net of observed LP gas, grouped by range width,
   holding time, LP type and cohort (opened before / inside the window).
4. **Lifetime result:** the share of window-active positions that beat holding over their whole life.
5. **Where LVR goes:** LVR from arbitrage → searcher kept / gas burned / builder margin / proposer
   payment.

**Guiding rule (roadmap):** measure what actually happened, reproduce the contract exactly where the
chain can check us, state limitations up front.

**Success criteria:**
- `uv run ulpe lp` regenerates every sub-project 3 table, chart and number in `results/` from validated
  data; `uv run ulpe all` runs the whole pipeline end to end (the paid fetch still needs its flag).
- Checks L1–L7 (section 9) pass and are enforced; reported checks are written.
- README TL;DR gains the sub-project 3 findings, every number quoted from `results/summary.json`.
- CI passes offline.

**Decisions made in brainstorming:**
- Scope: pool level **and** per position (option B of the first question).
- Positions open before the window: rebuilt from the pool's **full history** via one paid BigQuery
  query (option B; ~2.93 TB, covered by the user's Google Cloud trial credit).
- Lifetime P&L against holding is included (option 1); lifetime fees-vs-LVR decomposition is not.
- Engine: **contract-faithful accumulators** (approach 1): the pool's fee-growth accounting plus parallel
  LVR accumulators.
- Split: reference robustness (Tardis quotes, OKX trades) is **sub-project 4**; counterfactual LP
  strategies are **sub-project 5**.

**Out of scope:** sub-projects 4 and 5; LP gas before the window and in lifetime P&L; LP hedging on
other venues; lifetime fees-vs-LVR decomposition; the review clean-ups not listed in section 2
(duplicated helpers, dead code, CI hardening), which stay carried over.

## 2. Prerequisites (milestone M1, first tasks)

- **P1. Deterministic Binance reference.** `parse_agg_trades` keeps Binance's aggregated-trade ID
  (`agg_id`, first CSV column); `build_cex` sorts by `(ts_us, agg_id)`, so among trades sharing a
  microsecond the reference is the one with the highest ID (the latest). `align.reference_table`'s
  docstring is corrected. Interim data is rebuilt, `ulpe validate` re-run, `ulpe analyze` re-run, and
  every changed sub-project 2 headline number is listed in `docs/methodology.md` ("Changes in
  sub-project 3").
- **P2. Exact fees.** The replay produces `data/processed/swap_fees.parquet`: per swap, exact LP fee and
  protocol fee in raw units of the input token, from the step-by-step simulation (section 5), with the
  protocol cut per step `feeAmount // feeProtocol` as in the contract. `v3math.swap_fee_raw` and the
  `fee_amount_raw` column of `swaps.parquet` are retired; sub-project 2's `protocol_fee_usd` uses the
  exact value (valued at `P_cex(t0)` like every other amount in this sub-project). A3 stays an identity.
- **P3. End-of-window block check.** A2 additionally requires the last row of `blocks.parquet` to have
  timestamp ≥ `WINDOW_END − 12 s` and `blocks.max() ≥ events.block_number.max()`.
- **P4. TL;DR numbers in `summary.json`.** The sub-project 2 robustness rows by label and the 0 s
  size-bucket rows quoted in the README are added to `summary.json`.

## 3. Data

### 3.1 New inputs

| ID | What | Source | Used for |
|---|---|---|---|
| D1 | Pool `Mint`/`Burn`/`Collect` logs and NonfungiblePositionManager (NPM, `0xc36442b4a4522e871399cd717abdd847ab11fe88`) `IncreaseLiquidity`/`DecreaseLiquidity`/`Collect`/`Transfer` logs, 2021-05-04 → `WINDOW_END` | BigQuery `crypto_ethereum.logs`, **one paid query** (dry run 2,930 GB) | Every position's history and owner; lifetime P&L |
| D2 | At the snapshot block: pool `feeGrowthGlobal0X128`/`feeGrowthGlobal1X128`; for every initialized tick, `ticks(t).feeGrowthOutside0X128/1X128`; `pool.positions(key)` for every position key open at window start and `NPM.positions(tokenId)` for every NPM token of our pool open at window start (keys and tokens from D1) | RPC `eth_call`, batched via Multicall3 | Accumulator and contract-mirror start state |
| D3 | At the last window block: `pool.positions(key)` for every open position key, and `NPM.positions(tokenId)` for every open NPM token in our pool | RPC, batched | Check L3; uncollected fees at window end |
| D4 | `feeGrowthGlobal0/1X128` and `ticks(t)` fee fields for the ticks already sampled, at the 500 existing validation blocks | RPC, batched | Check L2 |
| D5 | Every transaction in the window (`block_number`, `transaction_index`, `from_address`, `to_address`, `value`, `receipt_gas_used`, `receipt_effective_gas_price`, `receipt_status`) and every trace with `value > 0` (`block_number`, `transaction_hash`, `from_address`, `to_address`, `value`, `trace_type`, `call_type`, `status`) | BigQuery (dry runs 32 GB and 288 GB) | Builder revenue, proposer payment, direct payments for every searcher |
| D6 | `proposer_payload_delivered` (`value`, `proposer_fee_recipient`, `builder_pubkey`) for 1,000 random window blocks, from the major MEV-Boost relays | Relay data APIs (free) | Cross-check of D5's proposer payment |
| D7 | Binance ETHUSDT 1-minute klines, 2021-05 → 2026-09 | data.binance.vision monthly zips, checksum-verified (free) | USD value of deposits for lifetime returns |
| D8 | `labels/lp_addresses.csv`: LP vaults and active managers, one row per address with name, category (`lp_vault`), source URL | Web-verified | LP type. Kept separate from `labels/addresses.csv` so sub-project 2's flow labels are unchanged |

All RPC work is plain `eth_call`/`eth_getCode` batched through Multicall3; it fits the free tier (the
`eth_getLogs` 10-block limit does not apply).

### 3.2 The paid fetch (D1)

- **Two stages.** Stage 1 runs one query over `crypto_ethereum.logs` for the window above with
  `address IN (pool, NPM)` and `topics[0]` in the 7 event signatures, writing its result to a
  destination table `<GCP_PROJECT>.ulpe_history.logs` (table expiration 7 days). Stage 2 queries that
  table only (cents): pool events as they are, plus NPM events whose `tokenId` belongs to our pool. A
  token belongs to our pool when one of its `IncreaseLiquidity` events shares a transaction with a pool
  `Mint` whose owner is the NPM and whose `amount` equals the event's `liquidity`. Stage 2 results are
  downloaded to `data/raw/history/pool_events.parquet` and `npm_events.parquet` (atomic writes).
- **Safeguards.** `ulpe fetch-history` always prints the dry-run size; it refuses to run stage 1
  without `--confirm-cost`; `maximum_bytes_billed` is 3.1 TB; a sandbox-mode error is turned into a
  message asking the user to link billing. **Execution pauses before stage 1 and the user confirms in
  chat.** Stage 1 is skipped when the destination table already exists.

### 3.3 Data layout

```
data/raw/history/        pool_events.parquet, npm_events.parquet           (D1)
data/raw/chain_state/    snapshot_fees.parquet, end_positions.parquet,
                         sample_fees.parquet, owner_code.parquet           (D2–D4, eth_getCode)
data/raw/builders/       window_txs.parquet, window_traces.parquet         (D5)
data/raw/relays.parquet                                                    (D6)
data/raw/binance/        ETHUSDT-1m-YYYY-MM.zip (+ .CHECKSUM)              (D7)
data/processed/          swap_fees.parquet, swap_steps.parquet, positions.parquet,
                         position_flows.parquet, lp_blocks.parquet
labels/lp_addresses.csv                                                    (D8, committed)
results/                 lp_checks.json/.md, lp_pnl.md, lvr_daily.csv, vol_regimes.md,
                         lp_groups.csv/.md, positions.csv, lifetime.md, lvr_destination.md,
                         figures/7–12
```

## 4. Positions

- **NPM positions:** one position per `tokenId` from its first `IncreaseLiquidity` to the end of its
  history, matched one to one with the pool's `Mint`/`Burn` (same transaction, owner = NPM, same
  liquidity). The **LP** is the token's owner when the position is closed (liquidity reaches 0 and is
  never increased again) or at `WINDOW_END`, from `Transfer` events; a position with an owner change
  while it holds liquidity is flagged `transferred`.
- **Direct positions:** keyed as the contract keys them, `(owner, tick_lower, tick_upper)`, and split
  into separate positions each time the key's liquidity returns to 0.
- **Window-active:** a position with liquidity > 0 at any moment in `[WINDOW_START, WINDOW_END)`.
  Positions closed before the window are used only for check L5.
- **Start state:** replaying D1 up to the snapshot block gives every position's liquidity at window
  start; their per-tick sum must equal the snapshot tick book exactly (L5).
- **LP type** (first match): `jit` (minted and fully burned in the same block); `lp_vault` (LP in
  `labels/lp_addresses.csv`); `nft_wallet` (NPM position, LP has no code at `WINDOW_END`);
  `nft_contract` (NPM position, LP has code); `direct_other`.
- **Range width:** `(1.0001^(tick_upper − tick_lower) − 1) × 1e4` bp; buckets `<50`, `50–200`,
  `200–1000`, `1000–5000`, `≥5000` bp (the last includes full range).
- **Holding time in window:** `same_block`, `<1h`, `1h–1d`, `1d–7d`, `≥7d`, `whole_window` (open at
  both ends).

## 5. Engine

**Swap re-simulation (extends `v3swap.py`).** V3's exact-output path of `computeSwapStep` is ported, and
`swap(book, zero_for_one, amount_specified, sqrt_price_limit)` handles both signs of
`amount_specified` with per-step records (`sqrt_start`, `sqrt_end`, `liquidity`, `amount_in`,
`amount_out`, `fee_amount`, `tick_crossed`). Each logged swap is reproduced in the first mode that
matches its logged amounts and final `sqrtPriceX96` bit-exactly: (1) exact input of the logged input
amount; (2) exact output of the logged output amount; (3) "to price": exact input of an unlimited
amount with the logged final price as the limit. The step records go to `swap_steps.parquet`.

**Accumulator state (`lp/state.py`).** The replay state gains, as the contract keeps them:
`fee_growth_global0/1` (Q128 integers) and per initialized tick `fee_growth_outside0/1`; and, as floats,
`fee_usd_growth_global`, `lvr_growth_global[h]` (`h ∈ {0, 12}` seconds) and their per-tick outside
values. Per step:
- protocol cut `= fee_amount // feeProtocol` of the input token (0 when off);
- `fee_growth_global_in += (fee_amount − cut) × 2¹²⁸ // L` (Solidity `mulDiv`, floor);
- `fee_usd_growth_global += (fee_amount − cut) × USD price of the input token at P_cex(t0) / L`;
- `lvr_growth_global[h] += lvr_step[h] / L`;
- crossing a tick flips all its outside values (`outside = global − outside`), before the liquidity
  change, exactly as `Tick.cross`.
Mint/Burn initialise a tick's outside values as `Tick.update` does (global if `tick ≤ current`, else 0).

**Measured LVR of a step** (`token0` = USDC, `token1` = WETH, `P = P_cex(t0 + h)` USD per ETH):
`lvr_step[h] = −(Δusdc + Δeth × P)` where `Δ` are the pool's token changes **excluding the fee**
(input `amount_in`, output `−amount_out`, decimal-adjusted). It is signed: positive when the trade
gained against Binance. Each step also carries the swap's sub-project 2 flow label. `h = 0` is primary;
`h = 12` is a sensitivity; a step whose reference is null contributes 0 and is counted.

**Position settlement (`lp/positions.py`).** Two layers, kept separate:
- **Contract mirror.** Exactly what the chain stores, updated only by events: on every pool `Mint` and
  `Burn` (including amount-0 `Burn`s, which the NPM uses to poke) the pool position key adds
  `liquidity × (fee_growth_insideN − fee_growth_inside_lastN) // 2¹²⁸` (modular 256-bit subtraction)
  to `tokensOwedN` and stores the new `fee_growth_inside_lastN`; pool `Collect` reduces `tokensOwedN`.
  NPM tokens mirror the NPM's own accounting the same way on `IncreaseLiquidity`, `DecreaseLiquidity`
  and `Collect`. `fee_growth_inside` is computed from global and outside values as
  `Tick.getFeeGrowthInside`. Check L3 compares this layer with D3.
- **Attribution.** For the analysis, each position also accrues, over every interval between its own
  liquidity changes and the window boundaries, exact raw fees `liquidity × Δfee_growth_insideN // 2¹²⁸`,
  USD fees and LVR from float accumulators of the same shape: `fee_usd_growth` (per step
  `(fee_amount − cut) × USD price of the input token at P_cex(t0) / L`) and `lvr_growth[h]`. Window
  boundaries snapshot the attribution layer only and never change the contract mirror.

**Theoretical LVR (`lp/theory.py`), per block `b` with active liquidity `L_b` at block start:**
- `L_dec = L_raw × 1e−12` (USDC 6 decimals, WETH 18), `p_b = P_cex(t_b)`.
- realised variance `RV_b = Σ r²` of 1 s log returns of `P_cex` sampled as of each second in
  `[t_b, t_{b+1})`.
- `lvr_theory_b = RV_b × L_dec × √p_b / 4` (full range reduces to `σ²/8 × pool value`).
- **Fee-and-block-time adjustment** (Milionis, Moallemi, Roughgarden 2023, arXiv:2305.14604,
  Theorem 1 and Eq. 12): `P_trade = 1 / (1 + η)`, `η = √(2λ) × γ / σ`, with `γ = ln(1 + 0.0005)`,
  `λ = 1/12 s⁻¹`, `σ` the day's realised volatility per √second. Expected arbitrage profit
  `≈ lvr_theory × P_trade`, expected fees from arbitrage `≈ lvr_theory × (1 − P_trade)`. Both are
  reported daily against measured arbitrage LVR (searcher steps) and fees on searcher steps.
- **Sampling sensitivity:** the same with 1-minute returns.

**Volatility regimes:** daily realised volatility `σ_day = √(Σ_day r²)` of 1 s returns, annualised
`× √365`; the 92 days split into terciles (low/mid/high).

## 6. P&L

Per window-active position, in USD unless stated:
- `fees` (realised + uncollected, LP share), `lvr_0`, `lvr_12`, `gas` (window mint/burn/collect
  transactions: `receipt_gas_used × receipt_effective_gas_price × P_cex(t0)`, split equally across the
  positions the transaction touches).
- **Against rebalancing:** `pnl_rebal = fees − lvr_0 − gas` (12 s variant reported).
- **Against holding:** all values at the Binance price at the position's window exit `t_end` (close or
  `WINDOW_END`): `pnl_hold = V(position at t_end) + fees + Σ withdrawn − Σ deposited − gas`, where
  deposits and withdrawals are token amounts (a position open at `WINDOW_START` deposits its token
  amounts at that moment).
- **Rate:** `bp_per_day = pnl / time_weighted_value / days_active × 1e4`, `time_weighted_value`
  averaged over the position's blocks at `P_cex(t_b)`. Same-block (`jit`) positions use the value at
  mint and `days_active = 12 s / 86400 s`, and are reported in USD per swap as well.
- **Groups** (section 4 groupings, and cohort): count, Σ fees, Σ LVR, Σ gas, Σ pnl_rebal, Σ pnl_hold,
  share with `pnl_hold > 0`, liquidity-time-weighted `bp_per_day` with a 95% bootstrap interval over
  positions (1,000 resamples, seed 42). Pool-level daily series keep the sub-project 2 day bootstrap.

**Lifetime against holding** (window-active positions, whole history from D1):
- deposits and withdrawals: pool `Mint`/`Burn` amounts (direct) or NPM `IncreaseLiquidity`/
  `DecreaseLiquidity` amounts (NPM);
- fees: `Σ Collect − Σ withdrawn principal` (pool `Collect` for direct positions, NPM `Collect` for
  NPM positions), plus the uncollected fees at `WINDOW_END` from the engine (cross-checked with D3);
- `pnl_hold_life = (Σ withdrawn + fees + V_end − Σ deposited)` valued at the exit price;
  `return_life = pnl_hold_life / Σ deposits valued at their own time` (D7 1-minute close before the
  window, `P_cex` inside it);
- reported: share with `pnl_hold_life > 0` overall and by range width and lifetime holding time
  (`<1d`, `1–7d`, `7–30d`, `30–180d`, `≥180d`), and the median `return_life`.

## 7. Where LVR goes (`lp/destination.py`)

Per block in the window, from D5:
- **builder revenue** `R_b = Σ_tx gas_used × (effective_gas_price − base_fee) + Σ successful traces
  with value to the block's fee recipient` (excluding the fee recipient's own transactions);
- **proposer payment** `Q_b`: the value of the block's last transaction if it is sent from the fee
  recipient; if there is none, the fee recipient is treated as the proposer (`Q_b = R_b`);
- **builder margin** `R_b − Q_b` (may be negative when builders subsidise).

For every searcher transaction in our pool: `gross` (sub-project 2, 0 s), gas burned, its own builder
payment `B_tx` (priority fee + direct transfers to the fee recipient, from traces, so **all** searchers
are covered), split into proposer `B_tx × Q_b / R_b` and builder `B_tx × (1 − Q_b / R_b)`; kept
`= gross − burned − B_tx`. Single-pool / multi-pool scope as in sub-project 2 (multi-pool reported gross
only): sub-project 2's other-logs query (`data/blocks.fetch_bot_tx_logs`) is run for **all** searcher
transactions instead of the top bots' (a window logs scan; dry run first, covered by the trial credit),
written to `data/raw/builders/searcher_tx_other_logs.parquet`.

Reported (`lvr_destination.md`, waterfall figure): pool LVR (0 s) → LVR on searcher steps → kept /
gas burned / builder margin / proposer, in USD and shares; LVR on other flows shown separately.
**Limitation text (verbatim wherever the method is described):**
> The split of builder payments between builder and proposer uses each block's ratio of proposer payment
> to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments
> are identified as the block's last transaction from the fee recipient and cross-checked against relay
> data on a sample of blocks only.

## 8. Components

| Module | Responsibility |
|---|---|
| `v3swap.py` (extended) | Exact-output path, three reproduction modes, per-step records |
| `data/history.py` | D1 two-stage BigQuery fetch with the safeguards of section 3.2 |
| `data/chain_state.py` | D2–D4 and `eth_getCode` via Multicall3 through `RpcClient` |
| `data/builders.py` | D5 (guarded BigQuery, dry run, byte cap, atomic writes) |
| `data/relays.py` | D6, retries, cached |
| `data/binance.py` (extended) | D7 klines, checksum-verified |
| `lp/state.py` | Accumulator state on top of `TickBook` |
| `lp/positions.py` | Position identity, NPM matching, owners, settlement |
| `lp/engine.py` | Replay driver: history → start state → window replay → positions, steps, fees |
| `lp/pnl.py` | Window P&L, groups, bootstrap |
| `lp/lifetime.py` | Lifetime against holding |
| `lp/theory.py` | Theoretical LVR, `P_trade`, volatility regimes |
| `lp/destination.py` | Section 7 |
| `lp/checks.py` | L1–L7 and reported checks |
| `lp/analyze.py` | Orchestration of `ulpe lp`, results and `summary.json` keys (reusing `report.py`, `figures.py`, `io.py`) |

**CLI:** `fetch-history [--dry-run] [--confirm-cost]`, `fetch-chain-state`, `fetch-builders`,
`fetch-relays`, `fetch-price-history`, `lp`. `ulpe all` runs every step in order (fetches, build,
validate, analyze, lp) and stops with a message at `fetch-history` when D1 is missing and
`--confirm-cost` was not given. `lp` calls `require_validated()` and refuses to run with missing inputs,
naming the command to run.

**Error handling:** an unmatched NPM or pool event stops the run with its block and log index; nothing
is dropped silently. RPC errors never print the URL. All writes are atomic.

## 9. Checks (`results/lp_checks.json` / `.md`)

Gated (any failure → no results written):

| | Check | Pass rule |
|---|---|---|
| L1 | Swap reproduction | Every swap bit-exact in one of the three modes (section 5); counts by mode reported |
| L2 | Fee accumulators vs chain | At each of the 500 sample blocks, `feeGrowthGlobal0/1` and the sampled ticks' `feeGrowthOutside0/1` equal the engine's exactly |
| L3 | Open positions vs chain at `WINDOW_END` | For every open pool key and NPM token, the contract mirror's liquidity, `feeGrowthInside0/1LastX128` and `tokensOwed0/1` equal D3 exactly |
| L4 | Fees vs Collect | For every position fully closed and fully collected in the window, engine fees = collected − withdrawn principal, exactly in raw units |
| L5 | Start state | Σ position liquidity per tick at the snapshot block = snapshot tick book (`liquidity_net` and `liquidity_gross`) exactly; active liquidity = snapshot `liquidity` |
| L6 | Identities | Σ position fees = pool fees net of protocol cut, within 1 raw unit per step; Σ position LVR = pool LVR, relative error ≤ 1e−9; pool `lvr_0` = Σ swaps (total fee at `P_cex(t0)` + trader markout 0 s), relative error ≤ 1e−9 |
| L7 | History completeness | Every window `Mint`/`Burn` belongs to exactly one position; every NPM event of our tokens matches a pool event; D1's window events equal `events.parquet` |

Reported: relay vs on-chain proposer payment (match rate, within 1 wei and within 1%); traces vs
sub-project 2 Alchemy coinbase payments for the top 4 bots; LP-type coverage; flagged `transferred`
positions; steps with a null 12 s reference.

## 10. Results and documentation

- **Figures 7–12:** daily fees vs measured LVR; measured vs theoretical LVR (with and without the
  `P_trade` adjustment); fees − LVR by volatility tercile; `bp_per_day` by range width and LP type with
  intervals; lifetime "beat holding" shares; LVR destination as a true waterfall (floating bars).
- **README:** TL;DR gains three sub-project 3 findings with a caveat each; new sections "LP P&L" and
  "Where LVR goes"; Limitations extended; Reproduce gains the new commands and the cost note.
- **`docs/methodology.md`:** positions, accumulators, measured and theoretical LVR, P&L definitions,
  lifetime, destination, checks, and "Changes in sub-project 3" (P1/P2 effects on sub-project 2 numbers).
- **Limitations (README and methodology):** reference price (last Binance trade; sub-project 4 tests mid
  and OKX); theory assumes GBM and Poisson blocks (Ethereum slots are fixed 12 s), and 1 s realised
  variance includes order-flow noise; LP hedging and other holdings unobserved; LP gas outside the
  window and in lifetime P&L not counted; lifetime values before the window use ETHUSDT 1-minute
  closes; an NFT position's LP is its owner at close, and a vault stands for many depositors; the
  destination limitation text of section 7.

## 11. Testing

- `v3swap`: V3's published `SwapMath` test vectors for exact input and output; round trips; each
  reproduction mode on constructed swaps, including a price-limited one.
- `lp/state.py` + `positions.py`: a hand-built two-tick pool where fee and LVR growth, a tick crossing,
  and settlement are computed by hand; modular subtraction across a wrap; Σ positions = pool.
- NPM matching, ownership changes, direct-key splitting at zero liquidity; unmatched events raise.
- Theory: full-range case equals `σ²/8 × V`; `P_trade` against the paper's example values.
- Destination: self-built block, builder subsidy, a searcher tx with and without a direct payment.
- End to end on the committed fixture, extended with synthetic D1–D7 covering a `jit` position, a
  position open before the window, a transferred NFT, and one swap of each reproduction mode.
- Live tests (deselected by default) for each new fetcher. Gates: ruff, ruff format, mypy strict,
  pytest, CI.

## 12. Order of work and risks

Milestones, each ending with a real-data run and its checks, so problems surface before money is spent:

1. **M1** P1–P4; rebuild, re-validate, re-run sub-project 2; commit updated results with the change note.
2. **M2** swap engine; L1 on real data.
3. **M3** accumulators, D2, D4; L2 on real data (the engine matches the chain before the paid query).
4. **M4** user confirmation in chat → D1; positions, D3; L3, L4, L5, L7.
5. **M5** P&L, theory, regimes, lifetime (D7); L6.
6. **M6** D5, D6, D8; destination.
7. **M7** results, figures, README, methodology.

**Risks:**
- *Some swaps reproduce in none of the three modes* → L1 fails with the list; the plan rules on a fourth
  mode or on a documented tolerance before M3.
- *NPM matching ambiguity* (two equal-liquidity mints in one transaction) → match by log order within
  the transaction; unmatched raises.
- *Float drift in LVR accumulators* → L6 relative tolerance; if it fails, accumulate in `math.fsum`
  per block before adding to the global.
- *Trial credit or billing not linked* → fetch-history explains; nothing else depends on billing.
- *Relay APIs rate-limit* → cached, resumable, sample size can shrink (reported check only).
