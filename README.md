# uniswap-lp-economics

**Who makes money on Uniswap V3?** A swap-by-swap study of the USDC/WETH 0.05% pool on Ethereum
mainnet: LP fees vs loss-versus-rebalancing (LVR), and markouts of each swap against Binance.

[![CI](https://github.com/samuraixx-key/uniswap-lp-economics/actions/workflows/ci.yml/badge.svg)](https://github.com/samuraixx-key/uniswap-lp-economics/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **Status: work in progress.** Data pipeline under construction; no results yet.

## TL;DR

*To be filled in once results exist: the question, three key findings with numbers and caveats,
and one headline chart.*

## Contents

- [Data](#data) · [Method](#method) · [Results](#results) · [Limitations](#limitations)
- [Reproduce](#reproduce) · [Repo map](#repo-map) · [Further reading](#further-reading)

## Data

| Source | What | How |
|---|---|---|
| Uniswap V3 pool `0x88e6…5640` | Swap, Mint, Burn events, block timestamps, tx sender/recipient | BigQuery `bigquery-public-data.crypto_ethereum` |
| Binance | ETHUSDC trades (reference price) | [data.binance.vision](https://data.binance.vision) |
| Archive RPC | Pool `slot0` / `liquidity` at sampled blocks | Validation only |

Validation: pool state rebuilt from events is compared with on-chain state at random blocks;
the match rate will be reported here.

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

```bash
uv sync
uv run pytest
```

Pipeline commands will be added as the stages land. Copy `.env.example` to `.env` first.

## Repo map

```
src/uniswap_lp_economics/
  config.py   pool constants and settings from .env
  v3math.py   Uniswap V3 price conversions
tests/        unit tests
```

## Further reading

- Milionis, Moallemi, Roughgarden, Zhang (2022), *Automated Market Making and Loss-Versus-Rebalancing*.
- Adams et al. (2021), *Uniswap v3 Core* whitepaper.

## License and disclaimer

MIT. Research only; not financial advice.
