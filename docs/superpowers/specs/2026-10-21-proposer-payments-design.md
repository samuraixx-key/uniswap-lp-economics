# Proposer-payment detection: design

Date: 2026-10-21. Status: approved for planning.

## 1. Why

Section 15 of the methodology splits each block's builder revenue `R_b` between the builder and
the proposer using the proposer payment `Q_b`, found as the block's last transaction **from the
fee recipient**. 105,536 of the 659,799 window blocks (16.0%) have no such transaction and fall
back to "self-built" (`Q_b = R_b`, proposer share 1). Those blocks hold 37.7% of the primary
proposer total, and relay check R1 shows the fallback is mostly wrong: all 70 relay mismatches
over 1% are such blocks. So the README hedges with two splits (primary, share 1; sensitivity,
share 0.4915) and a hatched "Builders or proposers" slice in the hero.

**Goal:** make the proposer/builder split trustworthy enough that the README states **one**
split. A full payment ledger is not a goal: no README claim depends on one, and the relay sample
is more useful as a test of the rule than as a replacement for it.

**Success test:**

- The README, `results/lvr_destination.md` and the hero state one proposer/builder split; the
  sensitivity table, the `sensitivity_self_built` summary key and the hatched hero slice are gone.
- R1 mismatches (over 1%) drop from 70 to about 4.
- Whatever is still unexplained is stated as a share of blocks and of single-pool builder dollars.
- R1 is reported in three parts (blocks seen while choosing the rule, the retries, and a fresh
  stratified holdout; section 6), and the README's choice between one split and the two-split
  hedge follows the pre-registered decision of section 6, whichever way it goes.

## 2. What exploration already showed (2026-10-21, scratch scripts, nothing committed)

All from data already on disk (`data/raw/builders/block_revenue.parquet`, `data/raw/relays.parquet`,
the per-swap costs of `destination.searcher_costs`).

- **The 175-block gap.** The README and `lvr_destination.md` count 105,536 self-built blocks; a
  count of `last_from != miner` gives 105,361. The 175 are blocks with no transactions:
  `last_from` is null, and `block_split` (`lp/destination.py:37`, `~paid.fill_null(False)`) counts
  them as self-built. Their revenue is 0, so no dollar figure changes.
- **Payout addresses.** In 66 of the 70 R1 mismatches the proposer *was* paid in the block's last
  transaction, just from the builder's separate payout address rather than the fee recipient
  (Titan: fee recipient `0x4838…`, payout `0x9fc3…`); `last_value_wei` equals the relay value
  exactly. These 66 were seen before the rule in section 4 was fixed, so they are not a blind test.
- **The other 4.** All have fee recipient `0x3963…` and a last transaction of value 0 from
  another address; the payment is in an earlier transaction. They are left unexplained (no special
  rule).
- **Fee recipients that never pay.** Some fee recipients never send a block's last transaction
  and have no payout address, e.g. `0x388c…` (Lido's execution-layer rewards vault). Their last
  transactions are zero-value transfers from senders seen with hundreds of fee recipients. This
  fits locally built blocks where the proposer is the fee recipient, so `Q_b = R_b` is correct
  there. It is an inference; check R1c tests it.
- **Size of each class** (provisional rule of section 4 on current columns, N from 20 to 100 gives
  the same picture; shares of 659,799 blocks and of $1,443,431 single-pool builder payments):

  | Class | Blocks | Builder $ |
  |---|---|---|
  | paid by the fee recipient | 84.0% | 79.4% |
  | paid from a payout address | 6.7% | 20.6% ($296.7k) |
  | proposer is fee recipient | 8.5% | $23 |
  | unexplained | 0.73% | $630 (0.04%) |
  | empty | 0.03% | $0 |

- **Dry runs (free).** The block's last transaction with `to_address` and `receipt_gas_used`:
  **15.2 GB**. Adding `input` (to test for empty calldata): 194.8 GB. The 15.2 GB query is the
  one to run.
- **The 261 GB query is not needed.** It would look for payments outside the last transaction,
  via traces. After the payout rule the unexplained remainder is $630 (0.04% of builder dollars),
  too small to move the split. It is dropped, and `docs/roadmap.md` says why.

## 3. Data

One new BigQuery table, `data/raw/builders/last_tx.parquet`: per window block with transactions,
the last transaction's `block_number`, `to_address`, `receipt_gas_used` (the 15.2 GB query).
It joins to `block_revenue.parquet` on `block_number` (that table already has `last_from` and
`last_value_wei`). It goes through `fetch_builders` like the other three tables: the dry run prints
its size, a real run needs `--confirm-cost`, existing files are skipped. **The user sees the dry
run's byte count before the paid run.**

## 4. The block classes (fixed before R1 is re-run)

Each window block gets exactly one class, in this order:

1. **empty**: no transactions (`last_from` null). `R_b = Q_b = 0`.
2. **paid**: `last_from == miner` (as now). `Q_b = last_value_wei`.
3. **payout**: `last_from` is a payout address of the block's fee recipient F (below), this
   block's last value is > 0, and the last transaction's `to_address != F`. `Q_b = last_value_wei`.
4. **proposer is fee recipient**: F has no block in class 2 or 3 anywhere in the window.
   `Q_b = R_b` (the proposer receives the revenue directly).
5. **unexplained**: everything else. `Q_b = R_b` (share 1, the old primary rule); the dollar
   effect is bounded by the class's builder payments ($630 in exploration) and is reported.

**Payout address**, learned from chain data only: sender S is a payout address of F if S sent
the last transaction in at least **N = 50** of F's blocks, with value > 0 in at least **99%** of
them, and S != F. These two numbers are fixed here, before R1 is re-run; the exploration showed
the classes barely move for N from 20 to 100, and the report states that stability.

**Top-up check.** A last transaction from a payout address to F itself is not a proposer
payment; such blocks fail class 3 and fall to unexplained. Their count is reported (expected 0).

**Recipient type (reported, not a filter).** A plain ETH transfer to an ordinary wallet uses
exactly 21,000 gas. A payment with more gas went to a recipient that runs code. For each distinct
such recipient, read its code over RPC (`rpc.get_code`) at the first and last block it was paid
in the window:

- code starting `0xef0100` (an EIP-7702 delegation) → **7702 wallet**;
- empty code → **wallet** (the extra gas is calldata);
- other code → **contract**.

Only class 3 payments are typed (class 2 is the published method and unchanged; typing it would
mean tens of thousands of archive reads for no claim). If the two reads differ, any `0xef0100`
read makes the recipient a 7702 wallet; otherwise any other code makes it a contract; the number
of recipients whose reads differ is reported. Payments, blocks and dollars are reported by
recipient type (wallet, 7702 wallet, contract). All three stay in class 3. This is how the roadmap's carried-over 7702 item is handled for this
classification: a delegated EOA is named as a wallet, never counted as a contract.

## 5. Relay sample retries

`ulpe fetch-relays` re-queries, on resume, every not-found row whose `relays_unchecked` is set
(190 blocks today), instead of skipping all blocks already in the file. Rows where every relay
answered "not delivered" (41) are not retried. The bloXroute and Flashbots failures (timeouts, the
circuit breaker after about 600 Flashbots blocks) get a slower pace and a longer timeout; a relay
that still fails stays in `relays_unchecked` and the count is reported. The relay file gains a
column `round` recording how each row entered: `seen` (answered before this work), `retry`
(answered by the retry), `holdout` (below), so each part of section 6 is fixed by the data, not
by memory.

**Holdout round.** A third, blind sample, drawn before any relay call for it:

- Seed **44**, leaving out the existing 1,000 sample blocks, stratified by the chain-only class
  of section 4 (so it is drawn after `last_tx.parquet` is fetched and the classes are built):
  - **300 blocks from class 3** (payout): the rule under test, and where the $296.7k sits;
  - **300 blocks at random from classes 2, 4 and 5** together.
- The block list, the seed and each block's stratum are written to the raw data before the first
  relay query, and the rows get `round = holdout`.
- The same paced fetch and circuit breaker as the retries.

Why 300: about 77% of sampled blocks were found on a relay, which leaves about 230 class-3 blocks.
At a true match rate of 99% failing the bar below is very unlikely; at 90% passing it is very
unlikely. The roughly 50 class-3 blocks of a plain random 1,000 could only catch a rule that is
badly wrong.

## 6. Checks and the pre-registered decision

The checks are reported and never fail the pipeline (like R1 today). R1 is reported per class and
in three parts:

- **seen**: the 769 found blocks of round 1, looked at while choosing the rule;
- **retry**: the 190 blocks of round 2, reported on their own. They mostly test the unexplained
  class (27 of them, 14%, against 0.73% overall; 147 of the 190 were left unchecked by bloXroute
  only). The report says whether the unexplained blocks are bloXroute-delivered; if they are, the
  residual has one cause, and it is named.
- **holdout**: round 3, the blind test, reported per stratum.

The checks:

- **R1, value.** Relay value vs `Q_b`, within 1 wei and within 1%.
- **R1b, recipient.** For classes 2 and 3, the last transaction's `to_address` equals the relay's
  `proposer_fee_recipient`; every class-3 block that fails is listed.
- **R1c, proposer-is-fee-recipient.** A class-4 block relay-delivered with a
  `proposer_fee_recipient` different from the block's fee recipient means the class is wrong for
  that block. Reported, not pass/fail: the breaking blocks and their builder dollars are listed
  (the class holds $23, so it cannot move the split); the class definition is revisited later if
  any turn up.

**Pre-registered decision** (written here and committed before the holdout is fetched). Among
**found holdout blocks in class 3**:

- at least **95%** match the relay **within 1 wei** (the share within 1% is reported too), and
- at least **95%** pass **R1b**.

If both hold, the README, `lvr_destination.md` and the hero state **one split** (section 7).
Otherwise the rule is left as it is, the holdout result is published as it stands, and the README
keeps the **two-split hedge** (primary and sensitivity, as now, with the classes reported beside
it). Classes 2, 4 and 5 and the other two parts are reported but decide nothing.

## 7. What changes downstream

This section describes the one-split outcome. If the section 6 decision keeps the hedge, the
class tables, checks and roadmap changes still ship, but the sensitivity, the hatched hero slice
and the README's two splits stay, with the holdout result added.

- `lp/destination.py`: `block_split` builds the five classes (the empty-block fix replaces
  `~paid.fill_null(False)`); `sensitivity_self_built`, `paid_block_ratio` and
  `SELF_BUILT_SHARE_BASIS` go; the summary gains a per-class table (blocks, share of blocks,
  single-pool builder USD, share) and the recipient-type table. `LIMITATION_TEXT` is rewritten to
  describe the new rule and the unexplained remainder.
- `lp/checks.py`: R1 as in section 6.
- `results/lvr_destination.md`: one split, the class table, the residual sentence.
- Hero (`viz/hero.py`): the hatched "Builders or proposers" node and its caption go; builders and
  proposers are drawn from the one split. Its data-checked title and subtitle are re-checked.
- Re-run `ulpe lp` then `ulpe figures`, and check by eye the hero, figure 08 (bots keep, which
  shows builder payments) and every data-checked title or subtitle that quotes the split.
  (Figure 12 is the lifetime chart and does not show the split; the hero is the figure that does.)
- README: the "Where LVR goes" finding and the "Proposer versus builder" limitation state one
  split and the residual; methodology sections 15 and 16 (R1) rewritten to match.
- `docs/roadmap.md`: proposer-payment detection and the relay retries move to Done; the 261 GB
  query is recorded as dropped ($630 left, 0.04% of builder dollars); the 7702 item notes that this
  classification handles it; the paid BigQuery spend gains the 15.2 GB.

## 8. Non-goals

- A full proposer-payment ledger, or payments found through traces (the 261 GB query).
- A special rule for the four `0x3963…` blocks.
- Using relay data to build the rule. The relay sample is only the test.
- The OKX order book and the synthetic-world additions (still on the roadmap).

## 9. Left to the builder

- How the class and recipient-type tables are laid out in the results files.
- The exact retry pacing and timeouts for bloXroute and Flashbots.
- Test fixtures: a small synthetic block table covering every class, the top-up case and each
  recipient type.
