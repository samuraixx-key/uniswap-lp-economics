# uniswap-lp-economics

**Who makes money on Uniswap V3?** A swap-by-swap study of the USDC/WETH 0.05% pool on Ethereum
mainnet: LP fees vs loss-versus-rebalancing (LVR), and markouts of each swap against Binance.

[![CI](https://github.com/samuraixx-key/uniswap-lp-economics/actions/workflows/ci.yml/badge.svg)](https://github.com/samuraixx-key/uniswap-lp-economics/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **Status: work in progress.** The data foundation is complete and validated (all six checks
> pass, see [Data](#data)). The analysis is pending; no results yet.

## TL;DR

*To be filled in once results exist: the question, three key findings with numbers and caveats,
and one headline chart.*

## Contents

- [Data](#data) · [Method](#method) · [Results](#results) · [Limitations](#limitations)
- [Reproduce](#reproduce) · [Repo map](#repo-map) · [Further reading](#further-reading)

## Data

Study window: `[2026-07-01, 2026-10-01)` UTC. Pool: USDC/WETH 0.05%
(`0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640`). Token0 is USDC (6 decimals), token1 is WETH
(18 decimals), fee 500 pips, tick spacing 10.

| Source | What | How |
|---|---|---|
| Uniswap V3 pool `0x88e6…5640` | All pool logs in the window (Swap, Mint, Burn, Collect, Flash, CollectProtocol), block timestamps, tx sender/recipient | BigQuery `bigquery-public-data.crypto_ethereum`, one file per month |
| Archive RPC | Full tick book at the snapshot block just before the window; pool state at 500 random blocks inside it | Starts the replay and validates it |
| Binance | ETHUSDC trades (ms timestamps, primary reference price) and ETHUSDT 1-second candles | [data.binance.vision](https://data.binance.vision), checksum-verified |

**What was collected.** 556,664 pool logs: 534,377 swaps, 5,616 mints, 8,115 burns, 8,119 collects,
57 flash and 380 collect_protocol. From Binance: 15,296,344 ETHUSDC trades and 7,948,800 ETHUSDT
1-second candles (complete).

**How liquidity is reconstructed.** Pool logs say what changed, not the full state, so the tick book
is rebuilt by replaying events in `(block, log_index)` order, starting from an on-chain snapshot of
the full tick book at block 25,433,938 (2026-06-30 23:59:59 UTC). State values (prices, liquidity)
are exact integers: Python `int` in code, `Int128` in Polars, and `Decimal(38, 0)` in the parquet
files (so pyarrow, pandas and DuckDB can read them too; use `uniswap_lp_economics.io.read_exact` to
get `Int128` back in Polars). Floats appear only in readable columns such as `amount_usdc`,
`amount_eth` and `price_usd`.

**Protocol fee.** Read from chain, `feeProtocol` is 68 (`0x44`) at the snapshot block and throughout
the window: the protocol takes 1/4 of every swap fee, in both tokens. There were no `SetFeeProtocol`
events in the window, and 380 `CollectProtocol` events. LP fee income in later stages therefore has
to be computed net of the protocol's quarter.

### Validation

Full report: [`data_validation/validation_report.md`](data_validation/validation_report.md)
(machine-readable: `validation_report.json`, which also lists a SHA-256 prefix of every input file
and the git commit). Overall status: **PASS**.

| Check | What it compares | Result |
|---|---|---|
| C1 | Active liquidity from the replayed tick book vs the `liquidity` value emitted in each Swap event | 534,377 swaps, 0 mismatches |
| C2 | Each swap's reported tick vs the tick implied by its `sqrtPriceX96` | 534,377 swaps, 0 mismatches (2 of them stop exactly on a tick boundary) |
| C3 | Replayed state vs on-chain `slot0`, `liquidity()` and `ticks()` at 500 random blocks (5 of them with the full set of initialized ticks) | 500/500 blocks, 17,625 ticks compared, 0 mismatches, 0 blocks missing data |
| C4 | Snapshot self-consistency | 1,557 initialized ticks; `liquidity_net` sums to 0; rebuilt active liquidity 2,811,825,879,343,074,188 equals on-chain `liquidity()` |
| C5 | Raw data integrity | 556,664 logs, 0 duplicates, 0 without a transaction, 0 outside the window, 0 of unknown event type; 6 Binance files, no bad checksums |
| C6 | Pool price vs the last Binance ETHUSDC trade before each swap | 534,377/534,377 matched; median gap 3.757 bp (gated: must be below 10 bp); 95th percentile 6.656 bp (reported, not bounded) |

What this proves and what it does not:

- C1 and C3 are exact-integer comparisons. Together they show that our reconstruction of in-range
  liquidity matches the chain at every swap and at 500 randomly chosen blocks. The fee and LVR
  calculations depend on that. It is a statement about this pool and this window, not a general
  proof that the replay code is correct for other pools.
- C3 checks a sample of blocks and ticks (the 20 initialized ticks nearest the price at each block,
  taken from the on-chain bitmap, plus the full book at 5 blocks), not every tick at every block.
  C1 covers every swap; C3 checks more fields (ticks not crossed by swaps) at sampled blocks.
- The C6 median is a sanity bound that catches gross errors such as a wrong decimal or an inverted
  price. It is not a finding, and it says nothing about who gains or loses from the pool/CEX gap.
- C5 reports a longest gap of 169.371924 s between consecutive Binance ETHUSDC trades. That is a
  property of the data, not a defect, but the CEX price at a swap can be that stale in quiet periods.

## Method

1. **Price discovery:** gap between the pool price and Binance, lead-lag, and who closes it.
2. **Markouts:** the price change after each swap at several horizons, by type of flow.
3. **LP P&L:** fees earned vs LVR (empirical and theoretical).
4. **Counterfactual LP strategies:** dynamic fees, range width, CEX hedging.

Details: `docs/methodology.md` (to be written).

## Results

*Pending.*

## Limitations

- DEX timing is block time (12 s slots); CEX timing is milliseconds. Markouts at very short
  horizons are approximate.
- Binance is used as the "true" price; other venues are ignored.
- Strategy experiments are counterfactual: they ignore how other traders would react.

## Reproduce

Requirements:

- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- A `.env` (copy `.env.example`) with `ETH_RPC_URL` set to an **archive** Ethereum RPC, e.g. the
  Alchemy (the free tier worked for us as of Oct 2026). Keep it private: the URL contains your API
  key. The code never prints or logs the RPC URL; server-supplied error messages are passed through.
- `gcloud auth application-default login` for BigQuery (the free sandbox worked for us as of
  Oct 2026), and `GCP_PROJECT` in `.env` set to your project.

```bash
uv sync
uv run pytest -q        # offline; includes the real-data fixture test
uv run ulpe all         # fetch anything missing, build, validate
```

`uv run pytest` needs no network or credentials: tests that touch the network are marked `live` and
skipped by default. The fixture test replays the first 400 real pool events of the window against a
matching slice of the on-chain tick book and runs checks C1 and C2 on them.

`ulpe all` can also be run one step at a time. Each fetch step skips what is already on disk:

```bash
uv run ulpe fetch-logs --start 2026-07-01 --end 2026-10-01   # BigQuery pool logs (--dry-run reports bytes scanned)
uv run ulpe fetch-snapshot                                   # tick book at the snapshot block (RPC)
uv run ulpe fetch-samples                                    # on-chain state at 500 random blocks (RPC)
uv run ulpe fetch-cex                                        # Binance ETHUSDC trades and ETHUSDT 1s candles
uv run ulpe build                                            # raw files -> interim tables
uv run ulpe validate                                         # checks C1-C6, writes data_validation/validation_report.{md,json}
```

`validate` (and `all`) exit non-zero if any check fails. Downloaded and built data goes under
`DATA_DIR` (default `./data`) and is git-ignored.

## Repo map

```
src/uniswap_lp_economics/
  abi.py            keccak, event topics and 32-byte word encoding
  config.py         pool constants, study window and settings from .env
  events.py         decode raw pool logs into typed values
  v3math.py         Uniswap V3 tick/price math and USDC/WETH price conversions
  tickbook.py       replayable per-tick liquidity state and active liquidity
  rpc.py            JSON-RPC client with retries, Multicall3 batching, pool call codecs
  snapshot.py       read the tick book and sampled state from chain
  io.py             parquet read/write for exact integers (Int128 in memory, Decimal(38,0) on disk)
  data/
    bigquery.py     download pool logs from BigQuery, one file per month
    binance.py      checksum-verified Binance downloads and parsing
  build.py          raw downloads -> interim tables (events, swaps, CEX prices)
  validate.py       checks C1-C6 and the validation report
  cli.py            `ulpe` command-line entry point
scripts/
  make_fixture.py   cut the small real-data test fixture
  migrate_int128_to_decimal.py   one-off: convert early raw files from Int128 to Decimal(38,0)
tests/              unit tests and the real-data fixture test
  fixtures/         real pool events and tick book for the offline fixture test
data_validation/    committed validation report (.md and .json)
docs/superpowers/   design spec and implementation plan for the data foundation
```

## Further reading

- Milionis, Moallemi, Roughgarden, Zhang (2022), *Automated Market Making and Loss-Versus-Rebalancing*.
- Adams et al. (2021), *Uniswap v3 Core* whitepaper.

## License and disclaimer

MIT. Research only; not financial advice.
