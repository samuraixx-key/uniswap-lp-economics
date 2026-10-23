# Where LVR goes

## 15. Where LVR goes

Per block in the window, from the builder tables (Ruling 4: aggregated inside BigQuery, because the
window has about 110 M transactions):

```
R_b = Σ_tx gas_used × (effective_gas_price − base_fee)     (transactions not sent by the fee recipient)
    + Σ successful trace payments to the fee recipient
Q_b = value of the block's last transaction if it is sent by the fee recipient;
      otherwise R_b (taken to be self-built: the fee recipient is the proposer; primary method)
proposer_share_b = Q_b / R_b      (0 when R_b = 0; above 1 when the builder subsidises)
```

A **trace payment** is a successful trace with value > 0 to the block's fee recipient, inside a
transaction the fee recipient did not send (its own transactions, e.g. unwrapping WETH, are
excluded), and not a `delegatecall`, `callcode` or `staticcall` (those move no value of their own).

Per searcher swap (sub-project 2 label), with the transaction's costs split across its swaps in
our pool by notional, in USD at `P_cex(t0)`:

```
gross          = trader_markout_usd(0)
gas_burned     = gas_used × base_fee
builder_paid   = gas_used × (effective_gas_price − base_fee) + trace payments to the fee recipient in the tx
proposer       = builder_paid × proposer_share_b
builder_margin = builder_paid − proposer
kept           = gross − gas_burned − builder_paid
```

Trace payments cover every searcher, not only the top bots of sub-project 2. A transaction
that both swaps and moves JIT liquidity (section 13) has its gas and payments counted here as the
searcher's cost and in section 13 as the LP's cost; the two analyses are never added together. **Scope:** a
transaction is single-pool when it emits no log from an address other than our pool, USDC, WETH and
its target (`COALESCE(to_address, the contract created)`); this is counted for every transaction
touching our pool. Multi-pool transactions are reported gross only.

The chain ([`results/lvr_destination.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/results/lvr_destination.md), the hero figure) runs: pool LVR
at 0 s (3,703,796.76 USD) → minus the other flows (−440,321.24) → LVR on searcher steps
(4,144,118.00) = LP fees (1,976,144.85) + protocol fees (658,714.87) + searcher gross
(1,509,258.29); gross = multi-pool gross (257,681.73) + single-pool gross (1,251,576.57); single-pool
gross = gas burned (9,715.89) + builder margin (848,648.09) + proposer (594,782.47) + kept
(−201,569.88). Shares are of the LVR on searcher steps: 0.4769, 0.1590, 0.0622, 0.0023, 0.2048,
0.1435 and −0.0486 (builder margin and proposer from the measured payments of sections 19 and
20; until section 20 the published split was the two-sided pair below). This section counts every searcher step, also any with no liquidity in range,
so its keys are named apart from the accrued-only totals of section 13. No swap needed a fallback:
0 swaps without an other-logs row, 0 in a block missing from the split, 0 with null costs.

**The self-built fallback, and a sensitivity.** 105,361 of the 659,799 window blocks (16.0%)
have transactions but no last transaction from the fee recipient, so the primary method gives
their proposer all of the builder revenue (the 175 blocks with no transactions were counted here
before proposer-payment detection; they carry no revenue). Section 19 measures what these blocks
paid: nearly all of their builder dollars sit in blocks that pay from a separate payout address,
and a blind relay holdout matches those payments to the wei. That measured split was not adopted
at first, because its pre-registered recipient check failed (section 19.5); a second
pre-registered test with a recipient check that follows forwarding contracts passed (section 20),
and the measured split is now the published one. The primary method and the sensitivity below
are kept as the record of what was published before; `summary.json` no longer carries
`sensitivity_self_built`.

These blocks carry 297,357.38 USD (0.2060) of the 1,443,430.55 USD of single-pool builder
payments (11,432 swaps), and 0.3767 of the primary proposer total. The sensitivity
(`sensitivity_self_built` in [`summary.json` at tag `forwarder-preregistered`](https://raw.githubusercontent.com/samuraixx-key/uniswap-lp-economics/forwarder-preregistered/results/summary.json),
before the class fix of section 20.1; the current results no longer compute it) gives
them the paid blocks' proposer share instead of 1:

```
self_built_proposer_share = Σ Q_b / Σ R_b over paid blocks = 0.4915
```

Revenue-weighted, because what is split is a sum of dollars: each wei of builder revenue counts
once, and a block with almost no revenue, whose per-block share can be very large when the
builder subsidises the proposer, cannot pull it. The median per-block share of the paid blocks
(0.6240) is reported beside it. Result, with shares of LVR on searcher steps:

| | primary (self-built share 1) | sensitivity (share 0.4915) |
|---|---|---|
| proposer, USD | 789,291.15 (0.1905) | 638,079.53 (0.1540) |
| builder margin, USD | 654,139.41 (0.1578) | 805,351.02 (0.1943) |

Their sum (0.3483), gas, kept and every other figure are the same under both. Builder margin
exceeds the proposer payment for any share below 0.77 in these blocks, so the ordering does not
depend on choosing the weighted ratio over the median. Both are superseded by the measured
split (proposer 594,782.47, 0.1435; builder margin 848,648.09, 0.2048), which lies outside the
pair: most of these blocks paid their proposer from a payout address, and paid less than either
method assumed.

Required limitation text (also in [the report](../../report/3-auction.md) and `results/lvr_destination.md`):

> The split of builder payments between builder and proposer uses each block's ratio of proposer payment to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments are identified as the block's last transaction, sent by the fee recipient or by a payout address learned from chain data, and tested on a blind stratified relay sample; blocks where neither applies give the proposer the whole builder revenue.

`kept` is still an upper bound, as in section 5: payments outside the transaction (a separate
transaction in the bundle, off-chain agreements) are missed, and failed transactions are not
seen. It is negative because builder margin plus proposer payment (0.2048 + 0.1435 = 0.3483 of
the LVR on searcher steps) exceeds the single-pool gross at 0 s (1,251,576.57 / 4,144,118.00 =
0.3020). Gross is measured at the block time, so kept is a small difference of large totals.
Sub-project 2's positive kept at 12 s (`kept_12s_usd`, +59,529.77 USD) covers the top 4 bots'
single-pool transactions only, not every searcher.

## 19. Proposer-payment detection

Design: [`docs/specs/2026-10-21-proposer-payments-design.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/docs/specs/2026-10-21-proposer-payments-design.md).
Its pre-registered parts (the rule, the holdout, the bar and the stopping rule) were committed
before any holdout relay call; the commit is tagged `holdout-preregistered`.

### 19.1 Data

A fourth builder table, `last_tx.parquet` (15.2 GB): each block's last transaction's `to_address`
and `receipt_gas_used`, 659,624 rows (every block with transactions). The `input` column was left
out (194.8 GB). `fetch-payout-code` reads, over RPC, the code of each payout recipient paid with
more than 21,000 gas, at the first and last block it was paid in: 161 reads, 93 recipients.

### 19.2 Block classes

Each window block gets one class, in this order, from chain data only:

1. **empty**: no transactions. `R_b = Q_b = 0`.
2. **paid**: the last transaction is sent by the fee recipient F. `Q_b` = its value.
3. **payout**: the last transaction is sent by a payout address of F, has value > 0, and does not
   go back to F. `Q_b` = its value. A sender S ≠ F is a payout address of F if S sent the last
   transaction in at least 50 of F's blocks, with value > 0 in at least 99% of them.
4. **proposer is fee recipient**: F has no block in class 2 or 3 anywhere in the window.
   `Q_b = R_b`.
5. **unexplained**: everything else. `Q_b = R_b`.

Counts in this section are from before the class fix of section 20.1 (the results in
[`summary.json` at tag `forwarder-preregistered`](https://raw.githubusercontent.com/samuraixx-key/uniswap-lp-economics/forwarder-preregistered/results/summary.json)); section 20.1 gives the
current ones.

| Class | Blocks | Share of blocks | Single-pool builder USD | Share |
|---|---|---|---|---|
| empty | 175 | 0.03% | 0.00 | 0% |
| paid | 554,263 | 84.00% | 1,146,073.18 | 79.40% |
| payout | 44,297 | 6.71% | 296,703.85 | 20.56% |
| proposer is fee recipient | 39,310 | 5.96% | 20.03 | 0.001% |
| unexplained | 21,754 | 3.30% | 633.49 | 0.044% |

At thresholds of 20 and 100 blocks instead of 50 the payout class has 44,640 and 44,233 blocks
(`class_counts_by_n` at that tag; 44,115 and 44,073 after the class fix). No payment from a payout address goes back to its fee
recipient (0 top-ups). Payout recipients by type, from the code reads (a payment of exactly
21,000 gas is a plain wallet without a read; code `0xef0100…` is an EIP-7702 delegated wallet,
counted as a wallet, not a contract; no recipient's two reads differ):

| Recipient | Payments | ETH paid | Single-pool builder USD |
|---|---|---|---|
| wallet | 9,490 | 176.52 | 59,269.43 |
| EIP-7702 wallet | 6 | 0.06 | 0.00 |
| contract | 34,801 | 677.73 | 237,434.42 |

**A known flaw of class 4, not fixed after the fact.** Two fee recipients that never pay from
themselves have a small qualifying payout pair: Lido's execution-layer rewards vault `0x388c…`
(160 payout blocks) and `0x7e2a…` (64). Because they then have a class-3 block, their other
16,967 blocks fall to unexplained instead of class 4. That is why the unexplained class has
21,754 blocks where the exploration, which keyed class 4 on paid blocks only, had 4,787 (the
same 4,787 are here). The dollars barely differ ($633.49 against about $630): these blocks carry
almost no builder payments. The rule was pre-registered, so it was not changed after the fact;
the fix was pre-registered with the second holdout instead and is in force from section 20 on
(class 4 then has 56,501 blocks and unexplained 4,787).

### 19.3 Relay rounds

`relays.parquet` gains a `round` column:

- **seen**: the original 1,000 blocks (seed 42), looked at while the rule was chosen. In 66 of the
  70 old mismatches the payment was the last transaction from a payout address, so this part is
  not blind.
- **retry**: the 190 blocks some relay never answered, asked again with a slower pace and a
  longer time-out. Flashbots answered (2 found); bloXroute max-profit failed on the other 188, in
  both retry passes. All 27 unexplained blocks in this round wait on bloXroute alone, so whether
  the unexplained blocks are bloXroute-built stays open.
- **holdout**: a fresh sample drawn after the rule was fixed (seed 44, the old sample left out),
  300 blocks from class 3 and 300 from classes 2, 4 and 5 together, written to
  `data/raw/relay_holdout.parquet` before its first relay call. 525 of the 600 were found; the 75
  not found all wait on bloXroute max-profit.

### 19.4 Checks and the result

R1 compares the relay's payment with `Q_b` of the payout rule; R1b compares the last
transaction's `to_address` with the relay's `proposer_fee_recipient`; R1c lists class-4 blocks a
relay delivered for a proposer other than the fee recipient.

| Round | Class | Found | Within 1 wei | Recipient matches |
|---|---|---|---|---|
| seen | paid | 699 | 699 | 377 |
| seen | payout | 66 | 66 | 33 |
| seen | unexplained | 4 | 0 | – |
| retry | paid | 2 | 2 | 1 |
| holdout | paid | 232 | 232 | 129 |
| holdout | payout | 289 | 289 | 132 |
| holdout | unexplained | 4 | 0 | – |

No class-4 block in any round was found on a relay (15 seen, 52 retry, 16 holdout sampled; 22, 80 and 26 after the class fix), so R1c
lists nothing: consistent with locally built blocks, as class 4 assumes.

**Pre-registered decision.** One split only if, among found holdout blocks in class 3, at least
95% match the relay within 1 wei and at least 95% pay the relay's `proposer_fee_recipient`
(a block without a relay recipient counts as a failure). Stopping rule: the holdout is fetched,
retried once, and the first `ulpe lp` after every holdout block has a row freezes the decision in
`data/raw/holdout_decision.json`; later runs publish the frozen decision and report any recomputed
one beside it. The frozen file:

```
n_found_payout        289
share_within_1_wei    1.0
share_within_1pct     1.0
share_recipient_match 0.4567   (132 / 289)
one_split             false
frozen                2026-10-22, after 600 of 600 holdout blocks had a row
```

So the published split stayed the two-sided pair of section 15, until the second holdout of
section 20 (`holdout_decision` in `summary.json` keeps this first decision; the file above is
never rewritten).

### 19.5 Why the recipient check failed: a forwarding contract

615 of the 616 recipient failures across all rounds (paid and payout classes) are payments into one
contract, `0xfeeeeee44046c3f61a8cc081e0918ef0de0a7ffc` (code `0x5f3580…`, about 29,000 gas per
payment), which passes the ETH on. R1b reads only the last transaction's `to_address`, so it
cannot see where the money ends up. The contract receives the last transaction in 291,274 of the
598,560 paid and payout-class blocks (48.7%), and it fails the primary method's own blocks the
same way: in the seen sample 377 of 699 paid blocks pass R1b, though all 699 match the relay's
payment to the wei. The bar therefore failed on the recipient check, not on the payments: every
found holdout block of the rule matches the relay's value exactly.

### 19.6 The rule's own split, not adopted

The payout rule's split was fixed with the rule before the run, so it is reported beside the
published pair, labelled as measured payments that were not adopted because the pre-registered
recipient check failed (`rule_split` in [`summary.json` at tag
`forwarder-preregistered`](https://raw.githubusercontent.com/samuraixx-key/uniswap-lp-economics/forwarder-preregistered/results/summary.json); the current results publish this split, so they
no longer compute it separately):

| | primary | sensitivity | measured payments; not adopted |
|---|---|---|---|
| proposer, USD | 789,291.15 (0.1905) | 638,079.53 (0.1540) | 594,782.47 (0.1435) |
| builder margin, USD | 654,139.41 (0.1578) | 805,351.02 (0.1943) | 848,648.09 (0.2048) |

Redefining R1b now and flipping the decision would be post hoc. A recipient check that follows
internal transfers through forwarders, with its bar written down before a fresh holdout (seed 45),
was run next (section 20); it passed, and this split, with the class fix, is now the published
one.

### 19.7 What was dropped

The 261 GB trace query planned to find payments outside the last transaction: after the payout
rule, $633.49 (0.044%) of single-pool builder dollars is unexplained, too little to move the split.

## 20. Recipient check through forwarders

Design: [`docs/specs/2026-10-21-forwarder-recipient-check-design.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/docs/specs/2026-10-21-forwarder-recipient-check-design.md).
Sections 3 to 6 of it (the class fix, the check, the holdout, the bar and the stopping rule) were
committed and tagged `forwarder-preregistered` before the seed-45 holdout was drawn; the code was
reviewed against them before the draw. No new check was computed on the seed-44 holdout.

### 20.1 The class fix

A payout address S of fee recipient F now also needs F to send the last transaction in at least
one of its own blocks. Two fee recipients never do: Lido's execution-layer rewards vault `0x388c…`
and `0x7e2a…`; their "payout addresses" sent about 0.006 ETH (0.01 ETH) with 21,000 gas to a
different wallet almost every time, withdrawals that happened to end the block. Their 224 class-3
blocks and 16,967 other blocks move to class 4:

| Class | Blocks | Share of blocks | Single-pool builder USD | Share |
|---|---|---|---|---|
| empty | 175 | 0.03% | 0.00 | 0% |
| paid | 554,263 | 84.00% | 1,146,073.18 | 79.40% |
| payout | 44,073 | 6.68% | 296,703.85 | 20.56% |
| proposer is fee recipient | 56,501 | 8.56% | 23.42 | 0.002% |
| unexplained | 4,787 | 0.73% | 630.11 | 0.044% |

At thresholds of 20 and 100 blocks the payout class has 44,115 and 44,073 blocks. The moved
blocks carry no single-pool builder dollars as payout blocks, so the payout rule's split is the
same as in section 19.6. The six EIP-7702 payments of section 19.2 were among the moved blocks;
no payout recipient is an EIP-7702 wallet now. None of the 45 earlier relay rows of the two fee
recipients was found on a relay, so no earlier found-block count changes.

### 20.2 The check, R1d

For a block in class 2 or 3 with last transaction `h`, recipient `a0` and value `v`, the payment
path starts at `a0` and follows, at most 3 times, the single internal transfer sent by the current
address in `h` with value ≥ `v`; it stops when there is not exactly one, or on a repeat. R1d
passes if the relay's `proposer_fee_recipient` is on the path. The forwarder `0xfeeeeee…7ffc` is
20 bytes of code (`0x5f358060e01c4218600f5760401cff5b5f5ffd00`): if the first 4 calldata bytes
equal the block timestamp it self-destructs to the address in calldata bytes 4–23, which since
Cancun only sends its balance there. Paths come from free RPC (`eth_getBlockByNumber` and
`alchemy_getAssetTransfers`, which reports that transfer), for the seed-45 blocks only
(`ulpe fetch-paths`, `data/raw/holdout2_paths.parquet`): 580 paths, 331 with one hop and 249 with
none. Every block's last transaction from the RPC matched the chain tables.

### 20.3 The second holdout and the result

Seed 45, every block already in `relays.parquet` left out, 300 blocks of class 3 and 300 of
classes 2, 4 and 5 (fixed classes), written to `data/raw/relay_holdout_2.parquet` before its
first relay call; relay rows `round = "holdout2"`. A copy of the relay file was taken before the
draw, and every later write of the file is refused if a row of an earlier round would change or
be added. bloXroute max-profit failed on 78 blocks in the fetch and again in the one retry; 522
of the 600 were found.

| Stratum | Class | Found | Within 1 wei | R1b | R1d |
|---|---|---|---|---|---|
| payout | payout | 290 | 290 | 117 | 290 |
| rest | paid | 232 | 232 | 108 | 232 |
| rest | proposer is fee recipient | 0 (20 sampled) | – | – | – |

No class-4 block was found on a relay (R1c lists nothing), and the rest stratum drew no
unexplained block. The frozen decision, `data/raw/holdout_decision_2.json`:

```
n_found_payout        290
share_within_1_wei    1.0
share_within_1pct     1.0
share_recipient_match 1.0      (R1d, 290 / 290)
one_split             true
frozen                2026-10-22, after 600 of 600 holdout-2 blocks had a relay row and every
                      paid/payout block a path
```

So `ulpe lp` publishes one split (`proposer_split: "one"`, `published_decision: "holdout2"` in
`summary.json`): proposer 594,782.47 USD (0.1435 of LVR on searcher steps), builder margin
848,648.09 USD (0.2048). The first decision stays in `holdout_decision`, unchanged.
