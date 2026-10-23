# Full methodology

This file defines every quantity in `results/` and gives its formula. Scope: the Uniswap V3
USDC/WETH 0.05% pool (`0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`) against Binance, window
`[2026-07-01, 2026-10-01)` UTC. Sections 1–8 cover sub-project 2 (design spec
[`docs/specs/2026-10-13-price-discovery-markouts-design.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/docs/specs/2026-10-13-price-discovery-markouts-design.md));
sections 9–17 cover sub-project 3, LP P&L and where LVR goes (design spec
[`docs/specs/2026-10-14-lp-pnl-lvr-design.md`](https://github.com/samuraixx-key/uniswap-lp-economics/blob/main/docs/specs/2026-10-14-lp-pnl-lvr-design.md)).
Where an implementation plan amended a spec, the ruling is cited ("Ruling n"); the sub-project 3
rulings that changed a definition or a number are listed in
[Changes in sub-project 3](lp.md#changes-in-sub-project-3). Sections 18–21 cover reference and timing
robustness, proposer payments, the recipient check through forwarders and the strategy
experiment, each with its own spec. Section 0 says why the main choices were made; section 22
lists every limitation. Numbers quoted here come from `results/`, except where a sentence names
another source.

Notation: `f` = pool swap fee = 500 pips = 0.0005; `c` = Binance trading fee assumed for the
arbitrage (0 or 1 bp); `P_cex(t)` = reference price at time `t` (section 2); pool prices are in
USDC per WETH; 1 bp = 10⁻⁴.

Contents: [0 Why these choices](../choices.md#0-why-these-choices) · [1 Data](../data.md#1-data-and-validation) · [2 Reference price](markouts.md#2-reference-price-and-time-zero) ·
[3 Markouts](markouts.md#3-markouts) · [4 Flow labels](markouts.md#4-flow-labels) ·
[5 Costs](discovery.md#5-costs-and-builder-payments) · [6 Price discovery](discovery.md#6-price-discovery) ·
[7 Available arbitrage](discovery.md#7-available-arbitrage) · [8 Checks](discovery.md#8-checks-a1a6)

Sub-project 3: [9 Positions](lp.md#9-positions) ·
[10 Accumulators](lp.md#10-fee-and-lvr-accumulators) · [11 Measured LVR](lp.md#11-measured-lvr) ·
[12 Theoretical LVR](lp.md#12-theoretical-lvr) · [13 P&L](lp.md#13-pl-in-the-window) ·
[14 Lifetime](lp.md#14-lifetime-pl-against-holding) · [15 Where LVR goes](destination.md#15-where-lvr-goes) ·
[16 Checks](lp.md#16-checks-l1l7-and-r1r6) · [17 Limitations](lp.md#17-limitations-of-sub-project-3) ·
[Changes in sub-project 3](lp.md#changes-in-sub-project-3)

Then: [18 Reference and timing](robustness.md#18-reference-and-timing-robustness-sub-project-4) ·
[19 Proposer payments](destination.md#19-proposer-payment-detection) ·
[20 Recipient check](destination.md#20-recipient-check-through-forwarders) ·
[21 Strategy experiment](strategy.md#21-strategy-experiment-phase-5) ·
[22 Limitations](../limitations.md#22-limitations-whole-project)
