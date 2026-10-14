# LP analysis checks: **PASS**

- generated_utc: `2026-10-14T21:21:13+00:00`
- git_commit: `7793710-dirty`

| Check | Result | Summary |
|---|---|---|
| L1 every swap reproduced bit-exactly | PASS | swaps=534377, unreproduced=0, by_mode={'to_price': 11595, 'exact_output': 25846, 'exact_input': 496936} |
| L2 fee accumulators match the chain | PASS | blocks=500, values_compared=18125, mismatches=0 |
| L3 position state matches the chain at both ends | PASS | compared=12263, mismatches=0, start_mismatches=0 |
| L4 fees equal Collect minus principal | PASS | positions_checked=3428, mismatches=0 |
| L5 positions rebuild the snapshot tick book | PASS | positions_open_at_snapshot=3837, ticks_compared=1557, tick_mismatches=0, active_liquidity_matches=True |
| L6 accounting identities | PASS | pool_lp_fees_raw=[1337421456289, 618857678632566990117], position_fees_raw=[1337421451419, 618857678632566985106], fee_shortfall_tolerance=620992, pool_lvr_0_usd=3703796.759283188, position_lvr_0_usd=3703796.7592831827, markout_identity_lvr_usd=3703796.7592831957, all_steps_lvr_0_usd=3703796.7592831883 |
| L7 history complete and every event assigned | PASS | window_liquidity_events=21850, missing_in_history=0, extra_in_history=0, without_position=0, noop_collects=8 |
