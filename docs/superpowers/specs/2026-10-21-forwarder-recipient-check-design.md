# Recipient check through forwarders: design

Date: 2026-10-21. Status: approved 2026-10-22, pre-registration (sections 3 to 6 are fixed before the seed-45
holdout is drawn; the commit that holds them is tagged `forwarder-preregistered`).

## 1. Why

Proposer-payment detection (methodology section 19, spec
[`2026-10-21-proposer-payments-design.md`](2026-10-21-proposer-payments-design.md)) measured the
payments but kept the two-sided proposer/builder split. On the blind seed-44 holdout every found
class-3 block matched the relay to the wei (289 of 289), but the pre-registered recipient check R1b
passed only 45.7% (bar 95%). R1b reads the last transaction's `to_address`; 615 of the 616
recipient failures across all rounds are payments into one forwarding contract,
`0xfeeeeee44046c3f61a8cc081e0918ef0de0a7ffc`, which passes the ETH on. It receives the last
transaction in 291,274 of the 598,560 paid and payout-class blocks (48.7%).

**Goal:** a recipient check that sees where a forwarded payment ends up, with its bar written down
before a fresh holdout is drawn, and the README's choice between one split and the two-split hedge
decided by that holdout, whichever way it goes.

**Not allowed:** redefining R1b and re-scoring the 289 seed-44 blocks already seen to fail. The
frozen decision in `data/raw/holdout_decision.json` stays the published record of the first test;
no new check is ever computed on seed-44 holdout blocks.

## 2. What exploration showed (2026-10-21, scratch scripts, nothing committed)

Only chain data and the seed-42 `seen` round were used; the seed-44 holdout was not looked at.

- **The forwarder's code** is 20 bytes, `0x5f358060e01c4218600f5760401cff5b5f5ffd00`: if the first
  4 bytes of calldata equal the block timestamp, `SELFDESTRUCT` to the address in calldata bytes
  4–23 (which, since Cancun, only sends the contract's whole balance there); otherwise revert. So
  the payment reaches that address in the same transaction, as an internal transfer.
- **Free RPC sees it.** The Alchemy endpoint the project already uses does not serve
  `debug_traceTransaction` or `trace_transaction` (HTTP 400), but `alchemy_getAssetTransfers`
  (category `internal`, already wrapped as `transfers.fetch_internal_transfers`) returns the
  forwarder's `SELFDESTRUCT` transfer with its transaction hash, recipient and value. The
  forwarder is also used in other transactions of the same block, so the transfer must be matched
  to the block's last transaction by hash (`eth_getBlockByNumber`).
- **Seen-round mechanism check.** Of the 765 found seed-42 blocks in classes 2 and 3, 355 fail
  R1b, all with the forwarder as `to_address`. Following one internal transfer of exactly the
  payment out of the forwarder in the last transaction reaches the relay's recipient in all 355
  (one hop each). These blocks were seen while designing the check, so this is a mechanism check,
  not a test; the test is section 6.
- **Class 4.** Only two fee recipients have a payout pair but never send a block's last
  transaction themselves: Lido's execution-layer rewards vault `0x388c…` (11,294 blocks, 160 in
  class 3) and `0x7e2a…` (5,905 blocks, 64 in class 3). Their "payout addresses" (`0xcd61…`,
  `0x8d18…`) send about 0.006 ETH (0.01 ETH) with 21,000 gas to a different wallet almost every
  time: withdrawals that happen to end the block, not proposer payments. With the fix of section 3
  the classes become (N = 50; N = 20 and 100 in brackets):

  | Class | Now | Fixed |
  |---|---|---|
  | paid | 554,263 | 554,263 |
  | payout | 44,297 | 44,073 (44,115; 44,073) |
  | proposer is fee recipient | 39,310 | 56,501 |
  | unexplained | 21,754 | 4,787 (4,745; 4,787) |
  | empty | 175 | 175 |

## 3. The class fix (pre-registered)

A sender S ≠ F is a payout address of fee recipient F only if, as now, S sent the last transaction
in at least 50 of F's blocks with value > 0 in at least 99% of them, **and F itself sent the last
transaction in at least one of its blocks** (F has a class-2 block). A payout address is a
builder's second paying wallet; a fee recipient that never pays from itself is a proposer, not a
builder. Everything else in the five classes is unchanged, including their order.

Effect: the 224 class-3 blocks of `0x388c…` and `0x7e2a…` and their other 16,967 blocks all go to
class 4 ("proposer is fee recipient", `Q_b = R_b`), as the exploration of the first spec had it.
Under the hedge the published primary and sensitivity splits do not change (they use only classes
2 and 1); the rule's own split changes for those 224 blocks. The fix is adopted whatever the
holdout shows: it is a definition, fixed here before any new relay data. R1c (a class-4 block a
relay delivered for someone other than the fee recipient) on the new holdout tests it and is
reported.

All rounds are reported with the fixed classes. Effect on the earlier rounds: 45 earlier relay
rows belong to these two fee recipients (7 seen, 28 retry, 10 seed-44 holdout), and none of them
was found on a relay, so no found-block count (R1, R1b, the recomputed first decision) changes;
only the not-found counts per class move. The frozen first decision file is not touched.

## 4. The recipient check through forwarders, R1d (pre-registered)

For a block in class 2 or 3 with last transaction hash `h`, recipient `a0` (`to_address`) and
value `v` (`last_value_wei`), the **payment path** is built from chain data:

1. Start at `a0`.
2. From the current address `a`, take the internal transfers in this block sent by `a` in
   transaction `h` with value ≥ `v`. If there is exactly one, append its recipient to the path
   and continue from it; otherwise stop.
3. Stop after 3 hops, or if the recipient is already on the path.

**R1d passes** if the relay's `proposer_fee_recipient` is on the path (compared lowercased). R1d
never fails a block that R1b passes (`a0` is on the path). A block with no relay recipient fails,
as in R1b. "Value ≥ v" rather than "= v" because a `SELFDESTRUCT` forwarder sends its whole
balance, which is the payment plus any dust it held.

The path is fetched over free RPC (one `eth_getBlockByNumber` per block, one
`alchemy_getAssetTransfers` per hop) **only for the blocks of the new holdout** (section 5) in
classes 2 and 3, into `data/raw/holdout2_paths.parquet` (`block_number`, `tx_hash`, `path`).
No BigQuery traces scan.

A path row is written only for a block fetched completely: the last transaction of
`eth_getBlockByNumber` (full transactions) must have `to` = `a0` and value = `v`, or the fetch
stops with an error (the chain tables and the RPC disagree; nothing is guessed). An RPC failure
after the client's retries writes no row; the fetch is resumable and is rerun until every block
has a row, which the stopping rule waits for. A path of just `[a0]` is a real result (no single
onward transfer), not a failure. (Builder's call, settled in review.)

## 5. The second holdout (pre-registered)

- **Draw:** seed **45**, excluding every block already in `relays.parquet` (the seed-42 sample,
  its retries and the seed-44 holdout), stratified by the fixed classes of section 3: **300 blocks
  from class 3** and **300 at random from classes 2, 4 and 5** together (the same strata and sizes
  as seed 44; `payouts.draw_holdout` with seed 45). Written to `data/raw/relay_holdout_2.parquet`
  before the first relay call and never redrawn.
- **Relay fetch:** the same paced fetch and circuit breaker as before; rows get
  `round = "holdout2"`. The retry pass for this round re-queries **only `holdout2` rows**; today's
  `retry_unchecked` re-queries not-found rows of every round (including the 75 seed-44 holdout
  rows), so it is restricted to one round.
- **Paths:** section 4, for every holdout-2 block in class 2 or 3, found on a relay or not.

**The published data is never touched.** Seed 45 has its own draw file
(`relay_holdout_2.parquet`), its own round label (`holdout2`), its own path file
(`holdout2_paths.parquet`) and its own decision file (`holdout_decision_2.json`).
`relay_holdout.parquet` and `holdout_decision.json` are only read. `relays.parquet` gains rows;
its existing `seen`, `retry` and `holdout` rows are kept byte-for-byte in value: each fetch that
rewrites the file first checks that those rows are unchanged and refuses to write otherwise, and a
copy of the file is taken before the first seed-45 call.

## 6. The decision and the stopping rule (pre-registered)

Among **found holdout-2 blocks in class 3** (fixed classes):

- at least **95%** match the relay **within 1 wei** (the share within 1% is reported too), and
- at least **95%** pass **R1d**.

If both hold, the README, `results/lvr_destination.md` and the hero state **one split**: the
payout rule's split under the fixed classes. Otherwise the two-split hedge stays, with both holdout
results published. The bar is the first holdout's, unchanged. Classes 2, 4 and 5 are reported
(R1, R1b, R1d, R1c) but decide nothing.

**Stopping rule.** The holdout is fetched, then retried once (`fetch-relays` run twice), and the
paths are fetched. The first `ulpe lp` run after every holdout-2 block has a relay row and every
class-2 or class-3 holdout-2 block has a path row freezes the decision in
`data/raw/holdout_decision_2.json`. Later runs publish the frozen decision and report any
recomputed one beside it. The number of found class-3 blocks is reported as it is; there is no
minimum. Until that file exists, the published decision is the first holdout's.

**Order of work.** This spec is committed and tagged `forwarder-preregistered` first. The class
fix, the draw, the path fetch and the decision code are then implemented and reviewed against
this text; only after that review is the seed-45 draw written and fetched. A code change after the
tag may fix how the code does what sections 3 to 6 say, never what they say. The outcome,
whichever it is, then goes into results, README, methodology and roadmap.

## 7. What changes downstream

- `lp/payouts.py`: the class fix; the seed-45 constant.
- `data/relays.py`: the second draw and fetch (file, seed and round as parameters of the existing
  holdout code); `retry_unchecked` keeps any holdout round.
- Path fetch over RPC, reusing `transfers.fetch_internal_transfers`, resumable, written in
  batches; a CLI step that runs it.
- `lp/checks.py`: R1d; the decision and freeze generalised to a second round and file; R1 reports
  `holdout2` per class and stratum next to the other rounds, with R1d where paths exist.
- `lp/analyze.py`: publishes the second decision once frozen (else the first), and both in
  `summary.json`. The one-split code path already exists (`proposer_split: "one"`, no
  sensitivity, `LIMITATION_TEXT`, no hatched hero slice).
- Results, figures, README, methodology (a new section 20, and section 19.2's "known flaw"
  pointing to it) and roadmap updated with the outcome, either way.

## 8. Non-goals

- Re-scoring the seed-44 holdout or the seen rounds with R1d (the seen-round check of section 2
  was a mechanism check during design, not part of any result).
- Paid traces, or traces for any blocks outside the second holdout.
- bloXroute max-profit (still down); a not-found block stays not found.
- A full proposer-payment ledger.

## 9. Left to the builder

- Command name and placement of the path fetch; checkpoint size.
- Table layout of the holdout-2 results in `lvr_destination.md` and `summary.json`.
- Test fixtures: a synthetic forwarder hop, a two-hop path, a split (two transfers, so the path
  stops), a loop, and the class fix on a fee recipient with a payout pair and no paid block.
