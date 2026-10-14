"""Raw downloads -> interim tables (events, swaps, CEX prices)."""

import json
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.config import DECIMALS0, DECIMALS1
from uniswap_lp_economics.data.binance import parse_agg_trades, parse_klines_close
from uniswap_lp_economics.events import decode_event
from uniswap_lp_economics.io import write_exact
from uniswap_lp_economics.v3math import Q96, fee_protocol_share, swap_fee_raw

EVENT_SCHEMA: dict[str, Any] = {
    "event": pl.String,
    "sender": pl.String,
    "recipient": pl.String,
    "owner": pl.String,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
    "sqrt_price_x96": pl.Int128,
    "liquidity": pl.Int128,
    "tick": pl.Int64,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "amount": pl.Int128,
    "paid0": pl.Int128,
    "paid1": pl.Int128,
    "fee_protocol0_new": pl.Int64,
    "fee_protocol1_new": pl.Int64,
}


def load_raw_logs(raw_dir: Path) -> pl.DataFrame:
    files = sorted(raw_dir.glob("pool_logs_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no pool logs in {raw_dir}; run `ulpe fetch-logs` first")
    return pl.read_parquet(files).sort("block_number", "log_index")


def load_snapshot_meta(raw_dir: Path) -> dict[str, int]:
    path = raw_dir / "snapshot_meta.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `ulpe fetch-snapshot` first")
    meta: dict[str, int] = json.loads(path.read_text())
    return meta


def decode_logs(logs: pl.DataFrame) -> pl.DataFrame:
    rows = [
        {k: v for k, v in decode_event(t, d).items() if k in EVENT_SCHEMA}
        for t, d in zip(logs["topics"].to_list(), logs["data"].to_list(), strict=True)
    ]
    decoded = pl.from_dicts(rows, schema=EVENT_SCHEMA)
    base = logs.drop("topics", "data").rename({"transaction_hash": "tx_hash"})
    sqrt = pl.col("sqrt_price_x96").cast(pl.Float64) / Q96
    return pl.concat([base, decoded], how="horizontal").with_columns(
        amount_usdc=pl.col("amount0").cast(pl.Float64) / 10**DECIMALS0,
        amount_eth=pl.col("amount1").cast(pl.Float64) / 10**DECIMALS1,
        price_usd=pl.when(pl.col("event") == "swap").then(
            10 ** (DECIMALS1 - DECIMALS0) / (sqrt * sqrt)
        ),
    )


def build_swaps(
    events: pl.DataFrame, start_sqrt_price_x96: int, start_fee_protocol: int
) -> pl.DataFrame:
    fee_protocols, fp = [], start_fee_protocol
    for kind, new0, new1 in events.select(
        "event", "fee_protocol0_new", "fee_protocol1_new"
    ).iter_rows():
        if kind == "set_fee_protocol":
            fp = new0 + (new1 << 4)
        elif kind == "swap":
            fee_protocols.append(fp)

    swaps = events.filter(pl.col("event") == "swap")
    a0, a1 = swaps["amount0"].to_list(), swaps["amount1"].to_list()
    zero_for_one = [x > 0 for x in a0]
    amount_in = [x if x > 0 else (y if y > 0 else 0) for x, y in zip(a0, a1, strict=True)]
    fee_token = [
        "USDC" if z else ("WETH" if y > 0 else None) for z, y in zip(zero_for_one, a1, strict=True)
    ]
    pre_sqrt = [start_sqrt_price_x96, *swaps["sqrt_price_x96"].to_list()[:-1]]
    pre = pl.Series("pre_sqrt_price_x96", pre_sqrt, dtype=pl.Int128).cast(pl.Float64) / Q96

    # direction follows zero_for_one (token0 in = buy ETH) so it always agrees with fee_token;
    # "none" only when both amounts are 0.
    direction = [
        "buy_eth" if z else ("sell_eth" if y > 0 else "none")
        for z, y in zip(zero_for_one, a1, strict=True)
    ]
    return swaps.with_columns(
        direction=pl.Series(direction, dtype=pl.String),
        zero_for_one=pl.Series(zero_for_one),
        notional_usd=pl.col("amount_usdc").abs(),
        fee_token=pl.Series(fee_token, dtype=pl.String),
        fee_amount_raw=pl.Series([swap_fee_raw(x) for x in amount_in], dtype=pl.Int128),
        pre_sqrt_price_x96=pl.Series(pre_sqrt, dtype=pl.Int128),
        pre_price_usd=10 ** (DECIMALS1 - DECIMALS0) / (pre * pre),
        fee_protocol=pl.Series(fee_protocols, dtype=pl.Int64),
        fee_protocol_share=pl.Series(
            [fee_protocol_share(f, z) for f, z in zip(fee_protocols, zero_for_one, strict=True)]
        ),
    ).with_columns(
        fee_usd=pl.when(pl.col("fee_token") == "USDC")
        .then(pl.col("fee_amount_raw").cast(pl.Float64) / 10**DECIMALS0)
        .when(pl.col("fee_token") == "WETH")
        .then(pl.col("fee_amount_raw").cast(pl.Float64) / 10**DECIMALS1 * pl.col("pre_price_usd"))
        .otherwise(0.0),
    )


def build_cex(raw_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    agg = sorted((raw_dir / "binance").glob("ETHUSDC-aggTrades-*.zip"))
    kl = sorted((raw_dir / "binance").glob("ETHUSDT-1s-*.zip"))
    if not agg or not kl:
        raise FileNotFoundError(
            f"Binance files missing in {raw_dir / 'binance'}; run `ulpe fetch-cex` first"
        )
    trades = pl.concat([parse_agg_trades(p) for p in agg]).sort("ts_us", "agg_trade_id")
    klines = pl.concat([parse_klines_close(p) for p in kl]).sort("ts_us")
    return trades, klines


def build_all(raw_dir: Path, interim_dir: Path) -> None:
    interim_dir.mkdir(parents=True, exist_ok=True)
    meta = load_snapshot_meta(raw_dir)
    events = decode_logs(load_raw_logs(raw_dir))
    write_exact(events, interim_dir / "events.parquet")
    swaps = build_swaps(events, int(meta["sqrt_price_x96"]), int(meta["fee_protocol"]))
    write_exact(swaps, interim_dir / "swaps.parquet")
    trades, klines = build_cex(raw_dir)
    write_exact(trades, interim_dir / "cex_ethusdc.parquet")
    write_exact(klines, interim_dir / "cex_ethusdt_1s.parquet")
    print(
        f"events {events.height:,}  swaps {swaps.height:,}  "
        f"cex trades {trades.height:,}  klines {klines.height:,}"
    )
