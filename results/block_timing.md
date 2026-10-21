# When blocks were sealed: winning-bid times

Winning-bid time = the earliest bid the delivering relay received with the delivered block hash, minus slot start, in ms. Only Titan, Flashbots and Aestus publish July 2026 bids; ultrasound, the largest relay, keeps no bid history for this window, so its blocks (and any it timed differently) are missing.

## Pooled

| metric | value |
|---|---|
| n_timed | 536 |
| n_queried | 1,000 |
| p10_ms | 779.0000 |
| p50_ms | 976.5000 |
| p90_ms | 2,567.5000 |

## By relay

| relay | n | p50_ms |
|---|---|---|
| https://aestus.live | 50 | 955.50 |
| https://boost-relay.flashbots.net | 21 | 549.00 |
| https://titanrelay.xyz | 465 | 984.00 |
