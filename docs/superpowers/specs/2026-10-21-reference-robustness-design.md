# Sub-project 4: reference and timing robustness: design

Date: 2026-10-21. Status: implemented (branch `reference-robustness`). Two changes made while
planning and building: the figure-12 label item was dropped (the chart redesign had already
fixed it), and every cell is a shift from the primary 0 s cell, so R6 checks the identity and
that anchor within the L6 tolerance rather than "to the cent" (plan Rulings 1-2, Task 6).

## 1. Why

The headline is that LPs lost to arbitrage: LP fees $2.64M against LVR(0 s) $3.70M, so fees − LVR
= −$1.06M (day bootstrap [−$1.53M, −$0.71M]). A reader at a trading firm will first object that this
comes from **our choice of reference price**, not from LPs actually losing money. Every number is
measured against one thing: the last Binance ETHUSDC trade at or before the block timestamp (t0).
They will push on it three ways:

- **Last trade isn't fair value.** It bounces between bid and ask, goes stale on quiet seconds, and
  comes from a single venue.
- **Clock.** t0 = block timestamp (slot start) is a convention we picked, not a measurement.
- **The interval doesn't cover it.** The day bootstrap measures sampling noise. A reference or
  timing bias is systematic and adds up in one direction on every swap.

**Success:** when this is done the README can truthfully say something of this form (numbers from
the exploration, to be replaced by computed ones):

> LPs lost $1.06M at the block timestamp. That's conservative: winning bids land about 1 s after
> slot start, where the loss is about $1.3M. A mid-price proxy or a USDT reference moves it by under
> $0.15M. It stays negative unless prices are read more than 3 s before the slot starts. $0.88M of
> the gap is the protocol's fee cut.

If the computed numbers say something else (for example, the sign flips inside the measured timing
band), that becomes the finding and is published as such.

## 2. What exploration already showed (2026-10-21, scratch scripts, nothing committed)

- Check L6 proves, per swap, LP fees − LVR = −(trader markout at 0 s) − protocol fees. So
  fees − LVR under any reference P and t0 offset d is a sum over swaps of
  `amount_usdc + amount_eth × P(t0 + d) − protocol_fee_usd(P)`, using the exact fees in
  `data/processed/swap_fees.parquet` and the swaps in `data/processed/aligned.parquet`. No new
  simulation is needed.
- fees − LVR, $M:

  | reference | −4 s | −3 s | −2 s | −1 s | 0 s | +1 s | +2 s | +4 s |
  |---|---|---|---|---|---|---|---|---|
  | Binance last trade (primary) | +0.04 | −0.22 | −0.48 | −0.79 | −1.06 | −1.32 | −1.40 | −1.47 |
  | Binance trade-side mid proxy | +0.20 | −0.06 | −0.33 | −0.65 | −0.92 | −1.19 | −1.32 | −1.44 |
  | Binance ETHUSDT 1 s close | +0.00 | −0.26 | −0.53 | −0.83 | −1.10 | −1.35 | −1.45 | −1.50 |

  LP fees stay at $2.644M within about $1k in every cell; all movement is in LVR. The primary 0 s
  cell reproduces the summary's LVR to the dollar; its LP fees are $316 lower, exactly the LP share
  of the 57 flash loans' fees, which the scratch script left out because they carry no LVR.
- Reference choice moves the headline by $0.1–0.2M; the t0 offset by about $0.27M per second near
  slot start. The sign flips between −3.9 s and −3.3 s. The curve flattens after about +2 s.
- **Protocol fees are $881k** (feeProtocol 68) and do not depend on the reference. Before the
  protocol's cut, total swap fees ($3.53M) nearly cover LVR ($3.70M).
- **Mid-price data.** Binance publishes no best bid/ask for 2026 (spot or futures bookTicker;
  futures bookTicker stopped in 2024-04). The trade-side proxy uses the aggTrades files already in
  `data/raw/binance`: buyer-initiated trades print at the ask, seller-initiated at the bid, and the
  proxy mid is the average of the latest of each. It is rough: the two sides are crossed 18% of the
  time (one side goes stale), median proxy spread 0.12 bp.
- **Relay timing.** Relays publish a received time (`timestamp_ms`) for every builder bid
  (`/relay/v1/data/bidtraces/builder_blocks_received`). Only some keep July 2026 history:

  | relay | share of the 769 identified sample blocks | keeps July bids? | winning bid, one test block |
  |---|---|---|---|
  | ultrasound | 77% | no | — |
  | Titan | 15% | yes | +944 ms after slot start |
  | Flashbots | 5% | yes | +877 ms |
  | Aestus | 2% | yes | +1,520 ms |

## 3. Goals

1. **Robustness table in the pipeline.** `ulpe lp` computes LP fees, LVR and fees − LVR for every
   reference × t0 offset and writes it to `results/`.
2. **Paired uncertainty.** Each cell's shift from the primary (Binance last trade, offset 0 s) gets
   a paired day-bootstrap interval: the same resampled days for both cells. This is what tells the
   reader whether "the mid proxy is $137k better" is real or noise.
3. **Measured block timing.** For a sample of window blocks delivered by relays that keep history,
   the winning bid's received time relative to slot start; reported as a distribution.
4. **A new figure** (section 6) showing the curve, the measured timing band and the protocol-fee
   line.
5. **README framing.** A new chapter after "Where LVR goes", and the TL;DR and limitations updated
   (section 7).
6. **Carried-over fixes** (section 8).

## 4. Non-goals and anti-goals

**Non-goals (moved to a later sub-project; `docs/roadmap.md` updated):**

- The OKX order book (ETH-USDC full L2, 2.9 GB). The mid effect it would sharpen is about $0.14M,
  which isn't the open question; the open question is timing, worth about $0.27M per second. It
  also mixes two effects (mid vs last trade, and OKX vs Binance).
- Proposer-payment detection (new query of about 261 GB) and relay-sample retries. They change who
  keeps the arbitrage profit, not whether LPs lost.
- The synthetic end-to-end world additions (transferred NFT, exact-output and to-price swaps).

**Anti-goals (would make this a failure even if it works):**

- **Changing the primary.** 0 s at the Binance last trade stays the headline everywhere. The
  measured t0 is reported next to it, never swapped in. Changing it would mean re-running and
  re-describing sub-projects 2 and 3.
- **Shaping the timing band to fit the message.** The band is drawn as observed, even if it comes
  out wide or lopsided or weakens the "conservative" claim.
- **Overclaiming coverage.** The timing measurement covers only Titan, Flashbots and Aestus blocks.
  Every place it appears says so, and says why ultrasound (the largest relay) is missing.
- **Hand-typed numbers.** Every number in the new figure title, the README chapter and the TL;DR
  comes from computed results, and titles are data-checked like the existing ones.
- **New paid queries or large downloads.** Everything uses data already on disk plus free relay
  API calls.

## 5. Method

### 5.1 References

| name | source | price at time t |
|---|---|---|
| `binance_last_trade` (primary) | ETHUSDC aggTrades (existing `reference_table`) | last trade at or before t |
| `binance_trade_side_mid` | the same aggTrades | mean of the latest buyer-initiated and the latest seller-initiated trade at or before t |
| `binance_ethusdt_1s_close` | ETHUSDT 1 s klines (existing `kline_reference_table`) | latest 1 s close at or before t |

All go through the existing `reference_at(t, table, window_end)`. The proxy's quality numbers
(crossed share, spread quantiles, mean distance from last trade) are written with the table.

### 5.2 Offsets

t0 + d for d from −5 s to +4 s in steps of 0.5 s (19 offsets), so the zero crossing is drawn, not
interpolated.

### 5.3 Totals per cell

Per swap, through the L6 identity in section 2, with the protocol fee and the WETH-denominated LP
fees priced at the same reference and offset as the cell. The 57 flash loans' fees are added to LP
fees as a constant (they carry no LVR), so the primary 0 s cell reconciles exactly to
`summary.json` (section 9).

### 5.4 Paired bootstrap

Resample UTC days with the existing seed and draw count. For each draw, compute every cell's
fees − LVR from the same days. Report, per cell:

- the point value;
- the shift from the primary 0 s cell, with its 95% paired interval;
- the primary line's own 95% interval at each offset (used for the figure's band).

### 5.5 Block timing

- **Sample:** the identified blocks in the existing relay sample (`data/raw/relays.parquet`)
  whose delivering relay keeps history (Titan, Flashbots, Aestus; about 177 blocks).
- **Per block:** query `builder_blocks_received?block_number=N` on the delivering relay and take
  the bid whose block hash is the delivered one (from `proposer_payload_delivered` on the same
  relay). The received time minus slot start (= the block timestamp) is the winning-bid offset.
- **Storage:** a resumable raw file next to `relays.parquet`, fetched by a new step and behind
  the same circuit-breaker pattern as the relay sample.
- **Result:** offset quantiles (10th, 50th, 90th) and count, by relay and pooled, plus fees − LVR
  on the primary line at the median offset.

## 6. The new figure: `13_reference_and_timing`

In the house style (`style.frame`, data-checked title, Inter, light theme):

- **x:** offset from slot start, −5 to +4 s. **y:** fees − LVR, $M.
- **Three lines, labelled at their right ends, no legend.** Primary solid; the other two lighter.
- **Zero line**, and a **dot on the primary line at 0 s** marking the headline.
- **Shaded band** over the 10th–90th percentile of measured winning-bid offsets, captioned
  "winning bids, Titan / Flashbots / Aestus blocks". Drawn as observed (anti-goal above).
- **Dashed horizontal line at −(protocol fees)**, labelled "protocol fee cut". Above it, total fees
  beat LVR before the protocol takes its share.
- **Bootstrap band on the primary line only.**
- **Title:** a data-checked statement of the form "LPs lose at every reference unless prices are
  read 3.5 s before the slot", built from the computed crossing offsets. If the data contradicts
  the form (for example, a crossing inside the timing band), the title states what the data shows.
- Reads only `results/` (a new table there, see section 7), like every other figure.

## 7. Outputs and README

- `results/reference_robustness.csv` and `.md`: the full reference × offset table with shifts and
  paired intervals, plus the proxy-quality numbers. The full table stays in `results/`, not in the
  README.
- `results/block_timing.md` (and the per-block CSV): the measured winning-bid offsets.
- `summary.json["lp"]` gains the few numbers the README quotes: fees − LVR at the median measured
  offset, the crossing offset per reference, the largest reference shift at 0 s, protocol fees as
  a share of the gap.
- **README:**
  - a new chapter "Is it the reference price?" after "Where LVR goes", with figure 13 and the
    success paragraph from section 1 in computed numbers;
  - the TL;DR states the protocol-fee split: before the protocol's cut, total fees nearly cover
    LVR, and the fee switch turns a borderline result into a clear loss;
  - the limitation bullets on reference price and t0 point to the new chapter;
  - the Contents line and repo map updated.
- `docs/methodology.md`: the trade-side proxy, the offset grid, the paired bootstrap and the
  block-timing method.

## 8. Carried-over fixes

- A5 and A6 show PASS instead of "reported": re-run `ulpe analyze` (and fix the code if the
  re-run still shows PASS).
- L1's `by_mode` dict order changes between runs: sort it like R3.
- `check_l1(engine_unmatched=0)`: remove the default so a caller can't silently skip the gate.
- `ulpe all` builds positions three times: build once.
- Figure 12's negative "kept" label overlaps its bar.
- Wherever a new owner classification appears, EIP-7702 delegated EOAs count as wallets (no new
  classification is planned here; this is a constraint).

## 9. Checks and testing

- **New reported check R6:** the primary 0 s cell equals the `summary.json` LP fees, LVR and
  fees − LVR to the cent.
- **Tests (TDD):** the proxy mid on a hand-built trade sequence (including a crossed case and a
  side that hasn't traded yet); the per-cell totals on a few synthetic swaps against hand-computed
  values; the paired bootstrap returns a zero-width shift for the primary against itself; the
  block-timing parser on a recorded relay response, including a block whose winning hash is absent;
  the figure renders from a small fixture table and its title check fails when the crossing moves.
- After the change, re-run `ulpe analyze`, `ulpe lp` and `ulpe figures`; existing results must not
  move except where section 8 says; every preview is checked by eye.

## 10. Constraints

- Never read `.env`; never print or log the RPC URL.
- No paid query in this sub-project; the relay calls are free and rate-limited politely.
- Renders stay byte-deterministic; ruff, mypy and the full test suite stay clean.
- Never use the word "toxicity".

## 11. Left to the builder

- Module layout (a new `lp/robustness.py` and `data/` fetch step are the natural fit).
- The exact relay request pacing and retry counts.
- How the figure's labels avoid each other at the right edge.
- Whether to widen the timing sample with extra random blocks on the history-keeping relays if the
  existing sample yields fewer than about 150 timed blocks (my call: do it, up to about 300).
