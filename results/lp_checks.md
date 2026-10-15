# LP analysis checks: **PASS**

- generated_utc: `2026-10-15T14:48:49+00:00`
- git_commit: `6c546d9`

| Check | Result | Summary |
|---|---|---|
| L1 every swap reproduced bit-exactly | PASS | swaps=534377, unreproduced=0, by_mode={'exact_input': 496936, 'exact_output': 25846, 'to_price': 11595}, engine_unmatched=0 |
| L2 fee accumulators match the chain | PASS | blocks=500, values_compared=18125, mismatches=0 |
| L3 position state matches the chain at both ends | PASS | compared=12263, mismatches=0, start_mismatches=0 |
| L4 fees equal Collect minus principal | PASS | positions_checked=3428, mismatches=0 |
| L5 positions rebuild the snapshot tick book | PASS | positions_open_at_snapshot=3837, ticks_compared=1557, tick_mismatches=0, active_liquidity_matches=True |
| L6 accounting identities | PASS | pool_lp_fees_raw=[1337421456289, 618857678632566990117], position_fees_raw=[1337421451419, 618857678632566985106], fee_shortfall_tolerance=620992, pool_lvr_0_usd=3703796.759283188, position_lvr_0_usd=3703796.7592831827, markout_identity_lvr_usd=3703796.7592831957, all_steps_lvr_0_usd=3703796.7592831883 |
| L7 history complete and every event assigned | PASS | window_liquidity_events=21850, missing_in_history=0, extra_in_history=0, without_position=0, noop_collects=8 |
| R1 relay vs on-chain proposer payment (reported) | reported | sampled=1000, found_on_a_relay=769, compared_with_on_chain=769, match_within_1_wei=699, match_within_1pct=699, by_block_type={'paid': {'sampled': 824, 'found': 699, 'match_within_1_wei': 699, 'match_within_1pct': 699, 'median_relay_value_over_revenue': 0.6344612952541893, 'relay_recipient_not_fee_recipient': 699}, 'self_built': {'sampled': 176, 'found': 70, 'match_within_1_wei': 0, 'match_within_1pct': 0, 'median_relay_value_over_revenue': 0.5561328198956222, 'relay_recipient_not_fee_recipient': 70}}, not_found_unchecked=190, not_found_all_answered=41 |
| R2 traces vs Alchemy builder payments, top bots (reported) | reported | alchemy_pool_txs_with_payment=56724, same_amount_in_traces=56724 |
| R3 LP-type coverage (reported) | reported | by_lp_type=[{'lp_type': 'jit', 'positions': 844, 'fee_usd': 4752.915576564617}, {'lp_type': 'lp_vault', 'positions': 111, 'fee_usd': 12151.36826076103}, {'lp_type': 'nft_wallet', 'positions': 5788, 'fee_usd': 2572025.8377652224}, {'lp_type': 'nft_contract', 'positions': 734, 'fee_usd': 38156.218421986516}, {'lp_type': 'direct_other', 'positions': 397, 'fee_usd': 17100.83084260079}] |
| R4 NFT positions transferred while open (reported) | reported | window_active=7874, transferred=570 |
| R5 steps without a 12 s reference (reported) | reported | steps=586360, without_12s_reference=0 |
