# LP positions, fees and LVR

## 9. Positions

### 9.1 Data added in sub-project 3

All git-ignored under `DATA_DIR/raw`, except the labels.

| File | Source | Content |
|---|---|---|
| `history/pool_events.parquet`, `history/npm_events.parquet` | BigQuery `crypto_ethereum.logs`, one paid query from the pool's creation (2021-05-04) to the window end; dry run 2.98 TB | Every pool `Mint`/`Burn`/`Collect`, and the NonfungiblePositionManager (NPM, `0xc364…fe88`) `IncreaseLiquidity`/`DecreaseLiquidity`/`Collect`/`Transfer` logs of tokens in our pool |
| `chain_state/snapshot_fees.parquet` | RPC at the snapshot block 25,433,938 | `feeGrowthGlobal0/1X128` and every initialized tick's `feeGrowthOutside0/1X128` |
| `chain_state/sample_fees.parquet` | RPC at the 500 sample blocks of check C3 | The same values for the sampled ticks (check L2) |
| `chain_state/start_positions.parquet`, `end_positions.parquet` | RPC at the snapshot block and at the window's last block | `pool.positions(key)` and `NPM.positions(tokenId)`: liquidity, `feeGrowthInside0/1LastX128`, `tokensOwed0/1` |
| `chain_state/owner_code.parquet` | `eth_getCode` at the window's last block | Whether each LP address has contract code, and its EIP-7702 delegate if any |
| `builders/block_revenue.parquet`, `pool_tx_direct_payments.parquet`, `pool_tx_other_logs.parquet` | BigQuery `transactions`, `traces` and `logs`, aggregated inside BigQuery (Ruling 4) | Section 15 |
| `relays.parquet` | MEV-Boost relay data APIs (free) | Relay-reported proposer payments for 1,000 random window blocks (check R1) |
| `binance/ETHUSDT-1m-YYYY-MM.zip` | data.binance.vision, checksum-verified | ETHUSDT 1-minute klines from the pool's creation month to the window start (section 14) |
| `labels/lp_addresses.csv` (committed) | Etherscan, one source link per address | LP vaults (section 9.3) |

The history query runs in two stages. Stage 1 selects the pool's and the NPM's logs with the seven
event signatures into a BigQuery table that expires after 7 days; stage 2 reads that table only:
pool events as they are, and NPM events of tokens in our pool. A token is in our pool when one of
its `IncreaseLiquidity` events shares a transaction with a pool `Mint` owned by the NPM with the
same liquidity.

### 9.2 Identity

- **NFT positions.** One position per NPM `tokenId`, over its whole life. Each NPM event is
  matched to the pool event the NPM emitted just before it in the same transaction:
  `IncreaseLiquidity` to a `Mint` owned by the NPM with the same liquidity, `DecreaseLiquidity`
  to a `Burn` of the same liquidity and range, `Collect` to a `Collect` on the same range (preceded
  by a `Burn` of 0, the NPM's "poke", when the token still holds liquidity). A token whose first
  `IncreaseLiquidity` matches no `Mint` in our pool belongs to another pool and is ignored; any
  other unmatched event stops the run with its block and log index.
- **NPM collect amounts.** The NPM's `Collect` event logs the amounts it requested,
  `min(amountMax, the token's tokens owed)`. The pool pays `min(requested, the NPM key's tokens
  owed)`, and the key's owed can be lower than the sum of its tokens' owed by floor rounding. So a
  pool `Collect` matches when its amounts are at most the NPM's in both tokens. The position's flow
  keeps the NPM amounts, which is the NPM's own accounting (and what checks L3 and L4 compare).
  Over the whole history there are 2,622 such shortfalls, the largest 48 raw USDC units and 44 wei.
- **Direct positions** (minted by any address other than the NPM) are keyed as the contract keys
  them, `(owner, tick_lower, tick_upper)`. A mint on a key with zero liquidity starts a new
  position; burns and collects go to the key's latest position.
- **Zero collects on keys never minted.** `UniswapV3Pool.collect` does not check that a position
  exists and emits `Collect(0, 0)` for any key. Such events are contract no-ops: no position, no
  flow. There are 179 in the history, 8 of them in the window (check L7).
- **Carried owed tokens.** When a direct key is minted again before its earlier position collected
  all it burned, the contract keeps the old tokens owed in the same slot, and the next collect pays
  them to the new position. The earlier position is flagged `carry_out` and the later one
  `carry_in` (the test: the earlier position burned more of either token than it collected). The
  split between the two cannot be recovered before the window, where fees are not known. Check L4
  skips both (section 16) and the lifetime statistics exclude flagged positions (section 14,
  `n_excluded_carry`); the window P&L is unaffected. In this run `n_excluded_carry` is 0.
- **LP.** For an NFT position, the token's owner when the position closes (its liquidity reaches 0
  and is never increased again), or at the window end, from the NPM `Transfer` events. For a
  direct position, the key's owner. An NFT position whose owner changed while it held liquidity is
  flagged `transferred` (check R4: 570 of the 7,874 window-active positions).
- **Window-active:** liquidity > 0 at some moment in `[WINDOW_START, WINDOW_END)`. A position whose
  only window event is a collect is not window-active. 7,874 positions are window-active; 3,837 of
  them were open at the snapshot (check L5).

### 9.3 LP types, range width, holding time and cohort

- **LP type** (first match): `jit` (not open at the window start, and its first deposit and its
  exit are in the same block, ending with no liquidity); `lp_vault` (the LP is in
  `labels/lp_addresses.csv`); `nft_wallet` (NFT position whose LP has no contract code at the
  window's last block); `nft_contract` (NFT position whose LP has code); `direct_other` (every other
  direct position, whatever its owner).
- **EIP-7702.** A delegated EOA has the code `0xef0100` followed by its 20-byte delegate. It is a
  wallet controlled by a private key, so `has_code` means real contract code and a delegated EOA
  counts as a wallet. Of the 4,112 addresses read (LPs and owners of window-active positions), 287
  have contract code and 861 are delegated EOAs (counts from the `eth_getCode` fetch,
  `owner_code.parquet`; they are not in `results/`).
- **LP vault labels.** An address is labelled `lp_vault` only if Etherscan names it as an LP vault
  or active manager. Four addresses qualify: a Gamma Hypervisor, a Harvest UniVaultProxy and two
  Enzyme external positions; each row of `labels/lp_addresses.csv` has its source link. Smart
  accounts, utility contracts and unverified contracts are not labelled, so they stay
  `nft_contract` or `direct_other`.
- **Range width:** `(1.0001^(tick_upper − tick_lower) − 1) × 10⁴` bp; buckets `<50`, `50-200`,
  `200-1000`, `1000-5000`, `>=5000` bp (the last includes full range).
- **Holding time in the window:** `same_block` (the `jit` positions), `whole_window` (open at both
  ends), else by exit time minus start time: `<1h`, `1h-1d`, `1d-7d`, `>=7d`.
- **Cohort:** `pre_window` (liquidity > 0 at the window start) or `in_window`.

## 10. Fee and LVR accumulators

**Swap reproduction.** Every swap of the window is re-simulated step by step from the replayed
state, and the first of three modes that reproduces its logged amounts and final `sqrtPriceX96`
bit-exactly is kept: (1) exact input of the logged input amount, (2) exact output of the logged
output amount, (3) "to price": exact input of an unlimited amount with the logged final price as
the limit. Each step records its start and end price, liquidity, `amount_in`, `amount_out`, fee and
crossed tick. Check L1: 496,936 swaps in mode 1, 25,846 in mode 2 and 11,595 in mode 3; none
unreproduced.

**Exact accumulators** (`lp/state.py`), as `UniswapV3Pool` and `Tick` keep them, all modulo 2²⁵⁶:

```
cut              = fee // feeProtocol nibble of the input token     (0 when off; 4 in this window)
lp_fee           = fee − cut
fee_growth_in   += lp_fee × 2¹²⁸ // L                               (only when L > 0)
cross tick t:      outside_t = global − outside_t                   (before the liquidity change)
init tick t:       outside_t = global if t ≤ current tick, else 0   (Tick.update; a cleared tick is re-initialized fresh)
inside(lo, hi)   = global − below(lo) − above(hi)                   (Tick.getFeeGrowthInside)
```

`L` is the step's active liquidity. A step with `L` = 0 pays the fee (and the protocol's cut) but
grows nothing and is marked not accrued; there are 0 such steps in this window.
**Flash loans** pay LP fees too: `UniswapV3Pool.flash` adds each token's paid fee, net of the
protocol's cut, to the fee growth exactly like a swap fee. The engine records it as one step per
token paid, with the flow label `flash` and no LVR; a WETH flash fee is valued at `P_cex(t0)` of
the most recent swap.

**Float accumulators**, with the same global/outside/inside mechanics, per step:

```
fee_usd_growth  += lp_fee × (USD per raw unit of the input token at P_cex(t0)) / L
lvr_growth[h]   += lvr_step[h] / L           h ∈ {0, 12} s (section 11)
```

USDC is taken at face value. The exact accumulators start from the chain's values at the snapshot
block; the float ones start at zero there, for the global value and for every tick (Ruling 3).
Only differences between two checkpoints are ever used, and "nothing accrued on either side since
the snapshot" is a valid starting state for the outside convention.

**Contract mirror and attribution** (`lp/ledger.py`), two layers kept apart:

- The **contract mirror** holds what the chain stores, updated only by events: every pool `Mint`
  and `Burn` (including the NPM's `Burn` of 0) adds `liquidity × (inside − inside_last) // 2¹²⁸`
  to the key's `tokensOwed` and stores the new `inside_last`; a pool `Collect` reduces
  `tokensOwed`. NPM tokens mirror the NPM's own accounting on `IncreaseLiquidity`,
  `DecreaseLiquidity` and `Collect`, reading the pool key's stored fee growth, as the NPM reads
  `pool.positions(key)`, never the ticks: the pool `Burn` just before a `DecreaseLiquidity` may have
  cleared them (Ruling 14). The mirror starts from the chain's `positions()` values at the snapshot,
  read for every pool key touched after the snapshot (a new position on a previously used key
  inherits that key's stored state) and every NPM token open at the window start. Check L3 compares
  the mirror with the chain at both ends.
- The **attribution layer** holds what each position earned in the window: exact raw fees
  `liquidity × Δinside // 2¹²⁸`, checkpointed at the position's own events and at the window
  boundaries (so its floors match the contract's), and USD fees and LVR from the float
  accumulators, also checkpointed at the first event of each new UTC day (Ruling 9). A position's
  `fees` are realised plus uncollected, LP share only.

## 11. Measured LVR

Per swap step (`token0` = USDC, `token1` = WETH, decimal-adjusted, `P = P_cex(t0 + h)`):

```
lvr_step[h] = −(Δusdc + Δeth × P)
```

where `Δ` are the pool's token changes **excluding the fee**: `+amount_in` of the input token and
`−amount_out` of the output token. It is signed: positive when the trade gained against Binance
(the pool gave a better price than Binance's), negative when the pool gained. `h` = 0 s is primary
and 12 s a sensitivity; a step without a 12 s reference would contribute 0 and be counted (check
R5: 0 of 586,360 steps).

Pool LVR is the sum over accrued steps: **3,703,796.76 USD at 0 s** and 4,089,325.49 USD at 12 s.
On searcher steps it is 4,144,118.00 USD; the other flows' steps sum to −440,321.24 USD, i.e. as a
whole they lost to the pool against Binance even before the fee.
This is a net, measured quantity: it counts every flow, not only arbitrage.

**Identity with the sub-project 2 markouts.** A markout's amounts include the fee and the LVR's
exclude it, so summed over each swap's steps

```
Σ_steps lvr_step[0] = trader_markout_usd(0) + total swap fee (LP + protocol) at P_cex(t0)
```

and therefore LP fees − LVR on a swap equals its sub-project 2 LP markout at 0 s. Check L6
enforces the identity over the window: 3,703,796.7592831883 USD from the steps against
3,703,796.7592831957 USD from the markouts (relative tolerance 1e-9).

**LP fees vs total fees.** The headline `fees_minus_lvr_usd` (−1,059,609.59 USD) uses LP fees, net
of the protocol's quarter (881,290.13 USD). The quarter is most of that gap. Total swap fees
(`daily` in `summary.json`, summed from `fees_usd + protocol_fee_usd` of
[`results/lvr_daily.csv`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lvr_daily.csv)) are 3,525,477.30 USD, short of LVR by
178,319.46 USD, with a 95% day-bootstrap interval of −566,463.71 to +91,433.73 (section 13). By
volatility tercile (`total_fees_minus_lvr_usd` in [`results/vol_regimes.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/vol_regimes.md)),
total fees − LVR is +31,703.62 (low), +54,157.72 (mid) and −264,180.80 USD (high), and LVR exceeds
total fees on 41 of the 92 days (against 79 for LP fees). This matches the sub-project 2 all-swaps trader markout of
+0.25 bp at 0 s (95% interval −0.14 to 0.77, section 3): by the identity above, the counterparties'
total markout is LVR minus total fees.

## 12. Theoretical LVR

For each interval `[t, t + Δ)` of a grid of Binance reference prices over the window, `Δ` = 1 s
(primary) or 60 s (sampling sensitivity):

```
r            = ln(P_cex(t + Δ) / P_cex(t))
lvr_theory   = r² × L_dec × √P_cex(t) / 4          L_dec = L_raw × 10⁻¹²
```

`L_raw` is the active liquidity in force at `t`: the end-of-block liquidity of the last block at or
before `t` (the state the next block's arbitrage trades against). For a full-range position
this reduces to the textbook `σ²/8 ×` pool value. Per UTC day, `RV_day = Σ r²` of the 1 s returns,
`σ_annual = √(365 × RV_day)` and `σ = √(RV_day / 86,400)` per √second.

**Fee and block-time adjustment** (Milionis, Moallemi, Roughgarden 2023, arXiv:2305.14604, Theorem 1
and Eq. 12):

```
P_trade = 1 / (1 + η),   η = √(2λ) × γ / σ,   γ = ln(1 + 0.0005),   λ = 1/12 s⁻¹
theory_arb      = theory_1s × P_trade           expected arbitrage profit
theory_arb_fees = theory_1s × (1 − P_trade)     expected fees paid by arbitrage
```

Window totals ([`results/lp_pnl.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lp_pnl.md)): theory 3,155,610.48 USD with 1 s
returns and 4,325,747.96 USD with 1-minute returns, against measured 3,703,796.76 USD;
`theory_arb` 931,857.47 USD and `theory_arb_fees` 2,223,753.00 USD. The model assumes geometric
Brownian motion and blocks arriving as a Poisson process with rate λ, while Ethereum slots are a
fixed 12 s. The 1-minute total is about a third higher than the 1 s one, so the sampling choice
matters as much as the model. Order-flow noise in Binance's last trade would push the 1 s
realised variance above the 1-minute one; it comes out below, so at 1 s stale stretches (the last
trade catching up with the price over several seconds) dominate, and noise does not.

**Volatility regimes.** The 92 days are ranked by `σ_annual` (ordinal rank) and split into terciles:
rank ≤ n/3 is `low` (30 days), ≤ 2n/3 `mid` (31), else `high` (31)
([`results/vol_regimes.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/vol_regimes.md)). The regime × LP type table sums the
per-day attribution of section 10.

## 13. P&L in the window

Per window-active position, in USD ([`results/positions.csv`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/positions.csv)):

- `fees`, `lvr_0`, `lvr_12` from the attribution layer.
- `gas`: every window transaction that changed the position (mint, burn, collect, increase,
  decrease, poke): `receipt_gas_used × receipt_effective_gas_price / 10¹⁸ × P_cex` at its block,
  split equally across the positions it touched. A transaction without a receipt, a block without a
  price, or a null gas field stops the run rather than costing 0.
- `direct`: direct ETH payments to the block's fee recipient in those same transactions (the
  `pool_tx_direct_payments` builder table of section 15), split and priced the same way. The
  priority fee inside `gas` is one half of a builder payment and a direct payment the other, so
  both are LP costs. A transaction that also swaps in the pool may pay for the swap rather than
  for the liquidity; `jit_own_swaps` below reports such transactions.
- **Against rebalancing:** `pnl_rebal = fees − lvr_0 − gas − direct` (and `pnl_rebal_12` with
  `lvr_12`).
- **Against holding:** everything the LP got out minus everything put in, all at the Binance price
  at the position's exit (its last removal, or the window end):
  `pnl_hold = V_exit + fees + Σ withdrawn − Σ deposited − gas − direct`. Deposits and withdrawals
  are token amounts; a position open at the window start deposits, at that moment, the token amounts it held
  at the snapshot pool price. This compares the LP with holding the deposited tokens.
- **Rate:** `bp_per_day = pnl_rebal / (twv × days) × 10⁴` (and `bp_per_day_hold` with `pnl_hold`).
  `twv`, the time-weighted value, is the mean of the position's USD value at each UTC hour start in
  `[t_start, t_exit)`: its liquidity at that time, as token amounts at the pool price of the block
  in force, valued at that block's `P_cex` (Ruling 5). A position open at no hour start uses the
  value of its first in-window deposit (or of its start holdings) at that block's price. `days` is
  `(t_exit − t_start) / 86,400 s`; a `jit` position counts one 12 s slot.
- **Groups** ([`results/lp_groups.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lp_groups.md)), by LP type, range width, holding
  time and cohort: count, Σ fees, Σ LVR, Σ gas, Σ direct, Σ `pnl_rebal`, Σ `pnl_hold`, the share
  with
  `pnl_hold > 0`, and `bp_per_day = Σ pnl_rebal / Σ (twv × days) × 10⁴`, i.e. weighted by
  value × time, with a 95% interval from a bootstrap over positions (1,000 resamples, seed 42,
  2.5th to 97.5th percentile of the same ratio).
- **JIT per swap** (spec section 6; `jit_per_swap` in `summary.json` and
  [`results/lp_pnl.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lp_pnl.md)): a `jit` position is active for the swaps of its
  block that lie, in log order, between its first liquidity add and its last removal. The jit
  totals of fees, LVR, gas, direct payments and both P&Ls are divided by the number of such
  position-swap pairs: 844 positions, 826 of them with at least one swap, 914 pairs; +3.90 USD per
  swap against rebalancing (fees 5.20, LVR −31.66, gas 21.63, direct 11.33). The median over
  positions with a swap is +0.09 USD per swap.
- **JIT transactions that also swap** (`jit_own_swaps` in `summary.json`): the transactions of
  `jit` positions that also hold a pool swap: 265 of 1,662, with 298 swaps whose 0 s trader
  markout sums to −14,295.61 USD. The `jit` positions carry 8,711.70 USD of gas and 10,305.31 USD
  of direct payments in those transactions (of 10,353.71 USD of JIT direct payments in
  all), counted per transaction from `cost_shares`: a JIT position usually has two transactions,
  mint and burn, and only the swapping ones count. Such a payment may be for the swap, and the
  rebalancing benchmark takes the operator's own swaps as free: JIT's 3,562.64 USD against
  rebalancing becomes about −10,733 USD with the swaps' markout added. The swaps lie outside the
  JIT positions' spans (all but 6, worth −0.01 USD, come before the first add or after the last
  removal), so they trade against other LPs and do not overlap the JIT positions' LVR.
- **Daily series** ([`results/lvr_daily.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lvr_daily.md)): per UTC day, LP fees,
  protocol fees, measured LVR at 0 s and 12 s, the searcher part (LVR, LP fees and protocol fees on
  searcher swaps), realised variance, `σ_annual`, the theoretical values and the regime.
- **Day bootstrap** (spec section 6: the pool-level daily series keep sub-project 2's day
  bootstrap; `daily` in `summary.json`): the window total of a daily series is resampled by drawing
  92 days with replacement, 1,000 times (seed 42), and the interval is the 2.5th to 97.5th
  percentile of the resampled totals. LP fees − LVR: −1,059,609.59 USD, 95% interval
  −1,533,757.96 to −712,591.77. Total fees − LVR: −178,319.46 USD, interval −566,463.71 to
  +91,433.73. As in section 3.3, days are treated as independent.

Headline totals (`lp_fees_usd`, `lvr_0_usd`, `lvr_12_usd`, and the accrued-only
`lvr_0_searcher_usd`, `lp_fees_searcher_usd`) sum accrued steps only: a step with no liquidity in
range paid no LP. Section 15 counts every searcher step; in this window the two coincide, as no
step lacked liquidity.

## 14. Lifetime P&L against holding

For every window-active position, over its whole history
([`results/lifetime.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lifetime.md)):

```
pnl_hold_life = (Σ collected + owed and accrued at the window end + V_end − Σ deposited) at P_exit
return_life   = pnl_hold_life / Σ deposits, each valued at its own time
beat_hold     = pnl_hold_life > 0
```

- Deposits are pool `Mint` amounts (direct) or NPM `IncreaseLiquidity` amounts (NFT); collected
  amounts are pool `Collect` (direct) or NPM `Collect` (NFT) and include the withdrawn principal,
  so withdrawals are not added again. Fees are implicit: collected minus withdrawn principal, plus
  what is still owed or accrued at the window end (from the engine).
- `P_exit` is the window-end price for an open position, else `P_cex` at the block of its last
  removal. Deposits inside the window are valued at `P_cex` of their block; deposits before it at
  the last ETHUSDT 1-minute close known at the deposit time (a bar's close is stamped at the bar's
  end). A close older than 3,600 s, a deposit block without a price, or a closed position without
  a removal stops the run.
- Positions flagged `carry_in` or `carry_out` (section 9.2) are left out of every share and median;
  `n_excluded_carry` reports how many (0 here). Lifetime holding buckets: `<1d`, `1-7d`,
  `7-30d`, `30-180d`, `>=180d`.
- The position's window costs (`gas + direct`, section 13) are subtracted from `pnl_hold_life`, so
  the window and lifetime results charge the same costs; gas and builder payments before the
  window are not observed and not charged.

## 16. Checks L1–L7 and R1–R6

Written to [`results/lp_checks.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lp_checks.md) (and `.json`). L1–L7 are gated: `ulpe
lp` computes everything, then writes the checks and, only if all pass, the results (`summary.json`
last). R1–R6 are reported (R6: section 18.5), never gate, and show "reported" in the Result column. All of L1–L7
pass in this run.

| Check | Rule | Result |
|---|---|---|
| L1 swap reproduction | Every swap bit-exact in one of the three modes (section 10), and none that the LP engine's own replay fails to reproduce | 534,377 swaps, 0 unreproduced; 496,936 exact input, 25,846 exact output, 11,595 to price; 0 unmatched in the engine |
| L2 fee accumulators vs chain | At each of the 500 sample blocks, `feeGrowthGlobal0/1` and the sampled ticks' `feeGrowthOutside0/1` equal the engine's exactly | 500 blocks, 18,125 values, 0 mismatches |
| L3 positions vs chain | The contract mirror's liquidity, `feeGrowthInside0/1LastX128` and `tokensOwed0/1` equal the chain's for every open pool key and NPM token at the window's last block, and the start state matches the rebuilt positions | 12,263 compared, 0 mismatches, 0 start mismatches |
| L4 fees vs Collect | For every position opened, closed and fully collected in the window (the chain owes nothing at the end), engine fees = collected − withdrawn principal, exactly in raw units. Positions that received carried owed tokens, or handed theirs on to a re-mint (section 9.2), are skipped | 3,428 positions, 0 mismatches |
| L5 start state | Σ liquidity of the positions open at the snapshot, per tick, equals the snapshot tick book (`liquidity_net` and `liquidity_gross`), and active liquidity matches | 3,837 positions, 1,557 ticks, 0 mismatches |
| L6 identities | Σ position fees ≤ pool LP fees, short by at most one raw unit per accrued step, one per window flow and two per position (Ruling 13); Σ position LVR = pool LVR and pool LVR = the markout identity (section 11), relative error ≤ 1e-9 | Pool LP fees 1,337,421,456,289 raw USDC and 618,857,678,632,566,990,117 wei; positions short by 4,870 and 5,011 (tolerance 620,992) |
| L7 history complete | The history's window `Mint`/`Burn` events equal `events.parquet`, each belongs to exactly one position, and every NPM event of our tokens matches a pool event | 21,850 liquidity events, 0 missing, 0 extra, 0 unassigned; 8 no-op zero collects |
| R1 relays | Relay-reported proposer payment vs `Q_b` of the payout rule (section 19), on 1,000 random window blocks, by block class and round (seen / retry / holdout), with R1b (recipient) and R1c (proposer is fee recipient) | 771 of the 1,000 found on a relay; 767 match within 1 wei (the same 767 within 1%): all 699 paid and 66 payout-address blocks found, 2 found in the retry, none of the 4 unexplained. Not found: 188 with bloXroute unchecked, 41 answered by every relay. Holdout and R1b, R1c: section 19 |
| R2 traces vs Alchemy | Top-bot payments to the fee recipient from sub-project 2's Alchemy transfers vs the trace payments, on transactions touching our pool | 56,724 of 56,724 equal |
| R3 LP-type coverage | Positions and fees by LP type | Table in `lp_checks.md`; 111 `lp_vault` positions |
| R4 transferred | NFT positions whose owner changed while open | 570 of 7,874 |
| R5 12 s reference | Steps without a 12 s reference | 0 of 586,360 |

What they prove and what they do not:

- L1–L3 and L5 are exact-integer comparisons with the chain: the engine reproduces every swap, the
  fee accumulators at 500 blocks, and every open position's stored state at both ends. The USD
  values and LVR rest on the float accumulators, which only L6 checks, as identities.
- L4 checks fees against what LPs actually collected, but only for positions that opened, closed
  and collected inside the window.
- **R1 sample.** The relay fetch has a circuit breaker: a relay that fails (time-out, server error
  or invalid JSON after retries) on 3 consecutive blocks is skipped for the rest of the run, and
  later blocks count as not checked on it. bloXroute max-profit timed out from the start and was
  skipped; Flashbots was skipped after about 600 blocks. The 190 blocks left unchecked were
  retried (section 19.3): Flashbots answered (2 found), bloXroute max-profit failed on all 188
  others. Under the old self-built fallback the 1,000 blocks gave 699 matches of 769 found, all 70
  mismatches being "self-built" blocks; under the payout rule of section 19 they give 767 of 771,
  and the 4 left are the unexplained class.

## 16a. Figures

`ulpe figures` renders every figure from `results/` only (`summary.json`, the results CSVs and
`results/figure_data/`), in light SVG with text as outlines, so a re-render with unchanged
inputs changes no file. The style (palette, Inter font, title block) is in `viz/style.py`.

| Figure | Inputs |
|---|---|
| Hero: where the LVR on searcher swaps went | `summary.json` `lp.destination` |
| 1 What is LVR (schematic) | none |
| 2 A stale-pool episode (and GIF) | `figure_data/episode_blocks.csv`, `episode_cex.csv` |
| 3 The pool follows Binance | `figure_data/basis_hist.csv`, `episodes.csv`, `summary.json` `lead_lag` |
| 4 Markouts by flow | `markouts.csv` |
| 5 LVR and fees against volatility | `lvr_daily.csv` |
| 6 Cumulative fees vs LVR | `lvr_daily.csv`, `summary.json` `lp.daily` |
| 7 Measured vs theoretical LVR | `lvr_daily.csv` |
| 8 Do bots keep the edge | `summary.json` `arbitrage`, `bot_profit.csv` |
| 9 Every position | `positions.csv` |
| 10 P&L by group | `lp_groups.csv` |
| 11 One JIT block | `figure_data/jit_block.csv`, `positions.csv` |
| 12 Lifetime vs holding | `summary.json` `lp.lifetime*` |
| 13 Reference and timing | `reference_robustness.csv`, `summary.json` `lp.robustness`, `lp.protocol_fees_usd` |

**Episode selection (figure 2).** The day with the largest measured LVR (0 s; the earliest on
ties); within it, the 20-block stretch with the largest absolute Binance log move; the figure shows
32 blocks starting 4 blocks before that stretch (fewer at the day's edges).

**JIT block selection (figure 11).** Among JIT positions whose own transactions (mint and burn) also
hold a pool swap before the first liquidity add and one after the last removal, the one with the
largest P&L vs rebalancing (then the lowest block, then the id). Without such a position, the most
profitable JIT position, and the figure says so. In the block shown, the operator's first swap
moves the pool from $1,794.90 to $1,759.93; its liquidity then buys the next trader's ETH at that
low price, a "negative LVR" of $2,093.08. The position made $1,125.36 against rebalancing, but the
operator's own two swaps lost $1,088.90 against Binance at 0 s: all in, the operator came out
$36.47 ahead ([`results/figure_data/jit_block.csv`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/figure_data/jit_block.csv)).

**"$10k" framing (figure 10).** P&L per $10,000 of time-weighted position value per 30 days =
`bp_per_day × 30`, since `bp_per_day` is P&L per 10⁴ of value per day.

**Line of best fit (figure 5).** Ordinary least squares of log USD per day on log annualised
volatility, over days with positive LVR and fees; the break-even is where the two fits cross.

## 17. Limitations of sub-project 3

Merged into [section 22](../limitations.md#22-limitations-whole-project), with every other sub-project's limitations.

## Changes in sub-project 3

<details class="note" markdown>
<summary>Rulings that changed a definition or a number, and where the code departs from the spec</summary>


Sub-project 3 made the Binance reference deterministic. Before, when several trades shared a
microsecond, the reference was an arbitrary one of them. Now the latest aggregated trade ID wins
(section 2). It also added two checks to A2: the last block lies within one 12 s slot of the window
end, and the block series covers the last event. Re-running sub-project 2 with these changes
(`ulpe build`, `validate`, `analyze`; C1–C6 and A1–A6 all PASS) changed no reported number:

| metric | before | after |
|---|---|---|
| any number in `results/` | — | unchanged (largest relative difference 6e-15, from floating-point summation order) |

So the old sort already left same-microsecond trades in trade-ID order in this data. The new rule
makes that guaranteed rather than incidental.

Sub-project 3 also replaced the approximate protocol fee with the exact one (section 3). Before,
`protocol_fee_usd` was `ceil(amount_in × 500 / 10⁶) × 1/4`, with WETH valued at the pre-swap pool
price. Now every swap is re-simulated step by step: 534,377 swaps, all reproduced bit-exactly
(check L1: 496,936 as exact input, 25,846 as exact output, 11,595 to the logged price). The
protocol takes `fee // 4` of each step's fee, and WETH is valued at `P_cex(t0)`. The protocol fee
only enters the LP markout, which no published table reports, so again no reported number changed.

| metric | before | after |
|---|---|---|
| swaps whose raw fee differs from the approximation | — | 26,338 (by a few raw units each) |
| total protocol fee, USD | 881,671.39 | 881,290.13 |
| A3 largest residual, USD | 2.2e-11 | 7.0e-12 |
| any number in `results/` | — | unchanged (largest relative difference 7e-15) |

### Where the code departs from the sub-project 3 spec

Reviewed rulings during implementation changed several definitions in the design spec. Sections
9–17 describe the code; this list says what changed and why.

| Topic | Spec | Code, and why |
|---|---|---|
| Flash loans | Fee growth from swap steps only | `UniswapV3Pool.flash` also grows fee growth, so flash fees accrue to LPs: one step per token paid, labelled `flash`, no LVR (section 10). Without it, L2 fails |
| Zero collects | Every pool event belongs to a position | A `Collect(0, 0)` on a key never minted is a contract no-op: no position, no flow; 179 in the history, 8 in the window (section 9.2) |
| NPM collect match | Exact amounts | The NPM logs requested amounts and the pool pays `min(requested, key owed)`; the pool `Collect` may be lower. Matched when ≤ in both tokens; flows keep the NPM amounts; 2,622 shortfalls, at most 48 raw USDC units and 44 wei |
| Direct key re-minted before its owed is collected | Not covered | The old owed stays in the slot and goes to the new position. `carry_in`/`carry_out` flags; L4 skips positions that handed on or received owed tokens; flagged positions are excluded from lifetime statistics and counted in `n_excluded_carry` |
| NPM token accounting | Fee growth inside from the ticks | Read from the pool key's stored fee growth, as the NPM does (Ruling 14) |
| Start state | Keys and tokens open at the window start | Every pool key touched after the snapshot is read at the snapshot (a new position on an old key inherits its stored owed); NPM tokens open at the window start |
| L6 fee tolerance | 1 raw unit per step | Also one per window flow and two per position, never above the pool's (Ruling 13) |
| Owner code | `has_code` from `eth_getCode` | EIP-7702 delegated EOAs (code `0xef0100` + delegate) are wallets, not contracts: 861 of the 4,112 addresses read are delegated, 287 are real contracts |
| LP vault labels | Web-verified vaults and managers | Only addresses Etherscan names as vaults or managers: 4 addresses, with sources in `labels/lp_addresses.csv` |
| LP gas | Gas of window mint/burn/collect transactions | A missing receipt, block price or gas field stops the run instead of costing 0. Direct payments to the fee recipient in the same transactions are charged too (`direct`), as the other half of a builder payment (pre-merge review) |
| Lifetime costs | Not specified | The position's window gas and direct payments are subtracted, so window and lifetime results charge the same costs (pre-merge review) |
| Time-weighted value | Averaged over the position's blocks | Sampled at UTC hour starts (Ruling 5); a position open at no hour start is valued at its first in-window deposit, not the sum of its deposits |
| Lifetime prices | ETHUSDT 1-minute closes | A close older than 3,600 s before a deposit stops the run (a missing month file or a data gap) |
| Headline totals | Sums over steps | Fee and LVR totals sum accrued steps only; the destination counts every searcher step, so its keys are named apart (`lvr_on_searcher_swaps_usd`, …) from `lvr_0_searcher_usd`. Identical in this window (no step without liquidity) |
| Builder data (D5) | Download every window transaction and value trace (dry runs 32 GB and 288 GB) | Aggregated inside BigQuery into three tables (Ruling 4); trace payments exclude transactions sent by the fee recipient and `delegatecall`/`callcode`/`staticcall` traces; the other-logs target is `COALESCE(to_address, contract created)` and covers every pool transaction. The three queries scanned about 661 GB, against the spec's estimate of about 320 GB, mostly because of the joins that exclude the fee recipient's own transactions. Proposer-payment detection added a fourth table, each block's last transaction (`to_address`, gas; 15.2 GB, section 19) |
| R2 | All top-bot payments vs traces | Restricted to transactions that touch our pool, the population the trace table covers |
| Theoretical LVR liquidity | Active liquidity `L_b` at block start | The end-of-block liquidity of the last block at or before the interval start: the state in force during the interval, which the next block's arbitrage trades against. Theory with 1 s returns moved from 3,158,845.51 to 3,155,610.48 USD |
| JIT per swap | "Reported in USD per swap" (no definition) | P&L over the swaps between the position's first add and last removal in its block, per position-swap pair (section 13) |
| Builder tables | `fetch-builders` (no flag) | A billable run needs `--confirm-cost`, like `fetch-history`; a dry run is free and needs none |
| Relay sample (R1) | Retries, cached | A circuit breaker skips a relay after 3 consecutive failed blocks: bloXroute max-profit timed out and was skipped, Flashbots was skipped after about 600 blocks; 769 of 1,000 blocks found, and 190 of the not-found blocks have relays that were not checked |


</details>
