# When blocks were sealed: winning-bid times

Winning-bid time = the earliest bid the delivering relay received with the delivered block hash, minus slot start, in ms. Only Titan, Flashbots and Aestus publish July 2026 bids; ultrasound, the largest relay, keeps no bid history for this window, so its blocks (and any it timed differently) are missing.

## Pooled

| metric | value |
|---|---|
| n_timed | 561 |
| n_queried | 1,000 |
| n_delivered_not_timed | 20 |
| p10_ms | 798.0000 |
| p50_ms | 979.0000 |
| p90_ms | 2,592.0000 |

## By relay

| relay | n | p50_ms |
|---|---|---|
| https://aestus.live | 50 | 955.50 |
| https://boost-relay.flashbots.net | 21 | 549.00 |
| https://titanrelay.xyz | 490 | 985.50 |
