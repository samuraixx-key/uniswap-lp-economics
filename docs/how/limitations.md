# 22. Limitations (whole project)

## Price discovery and markouts (sub-project 2)

> Builder payments are detected only as direct ETH transfers from the bot contract to the block's fee recipient within the same transaction. Payments routed elsewhere (another contract, a separate transaction in the bundle, off-chain agreements) are missed, so the reported net profit is an **upper bound** on what the bots keep. Binance-side trading fees, inventory and hedging costs are not observed.

- **Reference = last Binance trade.** There is no order-book data for the window, so no mid price,
  and Binance is the only reference venue. 73,139 swaps have a 0 s reference older than 5 s; the
  robustness variant without them changes little.
- **t0 = block timestamp** (whole seconds, the start of the 12-second slot), while Binance trades
  carry sub-second timestamps and the bots' decision and hedge times are not observed. Short-horizon
  markouts depend on this choice (the searchers' 0 s edge is 1.80 bp with t0 − 2 s). For LP fees
  − LVR, [section 18](methodology/robustness.md#18-reference-and-timing-robustness-sub-project-4) measures how far this goes.
- **Available arbitrage ignores gas, Binance fees beyond the 1 bp sensitivity, and Binance depth.**
  It assumes the arbitrage is the first trade at the block-start state, and a gap that stays open is
  counted again at each block start, so it is not what one arbitrageur could have taken.
- **Labels are a curated list plus heuristics.** `searcher` is a structural pattern (the pool's
  caller is the transaction's target), not a verified identity, and 0.11 of notional stays
  `other_contract`; the two largest unlabelled addresses are unverified contracts with no public
  name tag.
- **Failed bot transactions are not counted.** A reverted transaction, or one that exits without
  trading, emits no Swap log in the pool, so its gas never enters the cost side. This is a further
  reason the bots' net profit is an upper bound.
- **Multi-pool bot transactions get no cost breakdown:** their costs also pay for trades in other
  pools, so they are reported gross only.
- **Builder income** is income of the block's fee recipient, usually the builder; what the builder
  passes on to the proposer is not measured here (sub-project 3 splits it for searcher swaps, see
  [section 15](methodology/destination.md#15-where-lvr-goes)).
- **Statistics:** the bootstrap resamples UTC days and treats them as independent; for a thin group
  the interval is conditional on at least one active day and can be narrow.
- **Scope:** one pool and one quarter; nothing here is tested on other pools or periods.

## LP P&L and where LVR goes (sub-project 3)

> The split of builder payments between builder and proposer uses each block's ratio of proposer payment to builder revenue; how a builder prices an individual transaction is not observed. Proposer payments are identified as the block's last transaction, sent by the fee recipient or by a payout address learned from chain data, and tested on a blind stratified relay sample; blocks where neither applies give the proposer the whole builder revenue.

- **Reference price.** Measured LVR, fees in USD and every P&L use Binance's last ETHUSDC trade, as
  above. [section 18](methodology/robustness.md#18-reference-and-timing-robustness-sub-project-4) re-measures it against a
  trade-side mid proxy, ETHUSDT and other read times.
- **Theory** assumes geometric Brownian motion and blocks arriving as a Poisson process, while
  Ethereum slots are a fixed 12 s. The 1-minute version gives about a third more LVR than the
  1-second one. Order-flow noise in last trades would push 1-second realised variance above the
  1-minute one; it comes out below, so at 1 s stale stretches of the last trade (the price
  catching up over several seconds) dominate, and noise does not.
- **LP hedging and other holdings are not observed.** P&L against rebalancing is what an LP who
  could rebalance for free at Binance's last trade would have made; a hedged LP's real result also
  depends on the hedge's own costs.
- **LP gas and builder payments** are counted only for window transactions, in the window and
  the lifetime results alike; costs before the window are not observed. A JIT transaction that also
  swaps may pay the builder for the swap, and the rebalancing benchmark takes the LP's own swaps as
  free.
- **Lifetime values before the window** use ETHUSDT 1-minute closes (quoted in USDT).
- **Who the LP is.** An NFT position's LP is its owner at close (570 window-active positions
  changed owner while open), and a vault stands for many depositors. Only four vault addresses are
  labelled (those Etherscan names as vaults); other managers stay `nft_contract` or
  `direct_other`. EIP-7702 delegated wallets count as wallets.
- **Small accounting edges, reported:** NFT collects keep the amounts the position manager
  requested, which can exceed what the pool paid by up to 48 raw USDC units or 44 wei (2,622
  collects in the pool's history); a direct position re-minted before its owed tokens were collected
  hands them to the next position, and such positions are left out of the lifetime statistics (none
  among the window-active positions), but a carry of fees only (principal fully collected) is not
  flagged.
- **Where LVR goes:** "kept" is an upper bound (builder payments outside the transaction and
  failed transactions are missed). A transaction that both swaps and moves JIT liquidity has its
  gas and builder payments counted twice, as the searcher's cost here and as the LP's cost in the
  P&L tables: at most $19,017 in this window (the 265 such transactions).
  The two analyses are never added together. The proposer/builder split (proposers 14.4%, builders 20.5% of searcher LVR) comes
  from measured payments that passed a pre-registered relay test on the second attempt; the
  first attempt's failed recipient check stays published beside it (sections 19 and
  20). Blocks left unexplained ($630.11 of builder dollars, 0.044%) give the proposer the whole
  builder revenue. The sum (34.8%) does not depend on the split. The relay sample found 771 of
  1,000 blocks; bloXroute's max-profit relay, down throughout, left 188 of them and 75 and 78
  blocks of the two holdouts without an answer. 41 more not-found blocks of the sample were
  fetched before relay failures were recorded, so up to 229 may lack a bloXroute answer.
- **Path dependence.** P&L against holding, in the window and over a lifetime (53.5% of positions
  beat holding; 78% of those with a life of 180 days or more), depends on the price path over each
  position's life, and so on when it opened and closed.
- **Fees net of the protocol.** "Fees do not cover LVR" holds for LP fees; total swap fees fall
  short of LVR by much less ([section 11](methodology/lp.md#11-measured-lvr)).
- **Statistics:** the P&L intervals bootstrap positions and treat them as independent, though many
  positions share an LP.

## Reference and timing robustness (sub-project 4)

- **The mid price is a proxy.** There is no Binance bid/ask history for the window; the
  trade-side proxy is crossed at 18% of swap times. A true mid needs another venue's order book
  (OKX publishes one, 2.9 GB for ETH-USDC), which would mix venue and mid effects.
- **Timing covers the blocks three relays delivered.** Winning-bid times come from Titan,
  Aestus and Flashbots, the relays that keep bid history for the window: 561 of 1,000 sampled
  blocks, many also delivered through ultrasound. The 439 blocks none of the three delivered are
  missing. The received
  time is when the final block reached the relay, not when each searcher read a price.
- **The headline stays at the block timestamp.** Sub-projects 2 and 3 are not re-run at the
  measured time; the robustness table re-prices LP fees − LVR only, through the L6 identity.

## Strategy experiment (Phase 5)

- **Out of sample for the parameters, not for the analyst.** Every parameter was fixed on July and
  frozen before August–September was computed, but the window's aggregate results
  (sub-projects 2–4) were known when the hypothesis was written.
- **Price-takers.** A strategy position takes its share of the recorded swaps without changing
  them. 24 of the 27 tested cells are flagged because at their peak they hold more than 5% of the
  active liquidity (up to 84%); a position that large would change the swaps it trades against.
  The flag is in the table, and the verdict depends on the flagged cells; at $100k, where only
  12 are flagged, it is still inconclusive.
- **No routing model; fixed volume.** Where flow would go at a higher fee (the 0.3% pool, other
  venues) is not modelled. Kept flow is re-executed at its logged size at every fee; the
  break-even share assumes removed flow takes its fees and LVR with it in proportion and leaves
  the price path unchanged.
- **The fee model failed calibration**, so every fee number is model-only ([section 21.6](methodology/strategy.md#216-check-s3-calibration-july-reported)). The
  simulated arbitrage always trades first in the block and closes the whole gap to the fee band;
  real arbitrage sometimes trades after other swaps, and takes less.
- **Swap modes.** Kept swaps are re-executed in the mode check L1 found first (exact input, then
  exact output, then to price). A swap that was really exact output but reproduces as exact input
  at 5 bp is re-executed as exact input; at 5 bp the two cannot be told apart.
- **What is replaced.** "Searcher" is a contract that receives the transaction and calls the
  pool, not proven CEX-DEX arbitrage. 135 of the replaced swaps look like sandwich legs (0.34% of
  the replaced notional, −$712 gross at 0 s). Multi-pool searcher swaps are kept, though some of
  them are CEX-DEX arbitrage routed through other pools.
- **Hedge.** The ETHUSDC perpetual's 1-minute closes and funding files, with a 5 bp taker fee
  (1 and 10 bp as sensitivities); no depth, slippage or margin cost. Entry and exit of a strategy
  are free; only re-centrings pay gas and the taker fee, the same for every strategy.
- **Statistics:** 61 days, bootstrapped as independent days; with 27 cells, requiring every one
  inside ±δ is conservative, the right direction for a claim that something does not matter.
