import json
import zipfile
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from uniswap_lp_economics.build import build_all, build_swaps, decode_logs, load_raw_logs
from uniswap_lp_economics.events import SET_FEE_PROTOCOL_TOPIC, SWAP_TOPIC
from uniswap_lp_economics.v3math import eth_price_to_sqrt_price_x96


def word(v: int) -> str:
    return f"{v % 2**256:064x}"


ADDR = "0x" + "00" * 12 + "ab" * 20


def swap_log(
    block: int, idx: int, a0: int, a1: int, price: float, liq: int = 10**18
) -> dict[str, object]:
    sqrt = eth_price_to_sqrt_price_x96(price)
    return {
        "block_number": block,
        "block_timestamp": None,
        "transaction_hash": f"0x{block:064x}",
        "transaction_index": 0,
        "log_index": idx,
        "topics": [SWAP_TOPIC, ADDR, ADDR],
        "data": "0x" + "".join(word(v) for v in (a0, a1, sqrt, liq, -196_000)),
        "from_address": ADDR,
        "to_address": ADDR,
        "receipt_gas_used": 1,
        "receipt_effective_gas_price": 1,
        "max_priority_fee_per_gas": 1,
    }


def fee_log(block: int, idx: int, new0: int, new1: int) -> dict[str, object]:
    row = swap_log(block, idx, 0, 0, 2000.0)
    row["topics"] = [SET_FEE_PROTOCOL_TOPIC]
    row["data"] = "0x" + word(0) + word(0) + word(new0) + word(new1)
    return row


def logs(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows).with_columns(
        block_timestamp=pl.datetime(2026, 7, 1, time_zone="UTC")
        + pl.duration(seconds=pl.col("block_number") * 12)
    )


def test_decode_logs_exact_ints_and_readable_columns() -> None:
    ev = decode_logs(logs([swap_log(1, 0, 2_000 * 10**6, -(10**18), 2000.0)]))
    assert ev.schema["amount1"] == pl.Int128 and ev.schema["sqrt_price_x96"] == pl.Int128
    row = ev.row(0, named=True)
    assert row["event"] == "swap" and row["amount1"] == -(10**18)
    assert row["amount_usdc"] == 2000.0 and row["amount_eth"] == -1.0
    assert row["price_usd"] == pytest.approx(2000.0, rel=1e-9)
    assert row["tx_hash"] == f"0x{1:064x}"


def test_build_swaps_direction_fee_pre_price_and_protocol_share() -> None:
    ev = decode_logs(
        logs(
            [
                swap_log(1, 0, 2_000 * 10**6, -(10**18), 2001.0),  # trader sells USDC, buys ETH
                fee_log(2, 0, 4, 5),
                swap_log(3, 0, -2_000 * 10**6, 10**18, 1999.0),  # trader sells ETH
                swap_log(4, 0, 0, 0, 1999.0),  # zero-amount swap
                swap_log(5, 0, 1, 0, 1999.0),  # dust: 1 raw USDC in, no ETH out
                swap_log(6, 0, 0, 1, 1999.0),  # dust: 1 raw WETH in, no USDC out
            ]
        )
    )
    start = eth_price_to_sqrt_price_x96(2000.0)
    s = build_swaps(ev, start_sqrt_price_x96=start, start_fee_protocol=0)
    # Dust swaps (one amount is 0): direction must agree with zero_for_one and fee_token.
    assert s["direction"].to_list() == ["buy_eth", "sell_eth", "none", "buy_eth", "sell_eth"]
    assert s["zero_for_one"].to_list() == [True, False, False, True, False]
    assert s["fee_token"].to_list() == ["USDC", "WETH", None, "USDC", "WETH"]
    assert s["fee_amount_raw"].to_list() == [10**6, 5 * 10**14, 0, 1, 1]
    assert s["pre_sqrt_price_x96"].to_list()[0] == start
    assert s["pre_price_usd"].to_list()[1] == pytest.approx(2001.0, rel=1e-9)
    assert s["fee_usd"].to_list()[0] == pytest.approx(1.0)
    assert s["fee_usd"].to_list()[1] == pytest.approx(0.0005 * 2001.0, rel=1e-6)
    # Before the switch: 0. After SetFeeProtocol(4, 5): ETH-in swaps use token1's 1/5.
    # The zero-amount swap has no token0 input, so it also reads token1's share
    # (its fee is 0 anyway).
    assert s["fee_protocol_share"].to_list() == [0.0, 0.2, 0.2, 0.25, 0.2]


def test_missing_raw_logs_names_command(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ulpe fetch-logs"):
        load_raw_logs(tmp_path)


def test_build_all_writes_exact_ints_readable_outside_polars(tmp_path: Path) -> None:
    raw, interim = tmp_path / "raw", tmp_path / "interim"
    (raw / "binance").mkdir(parents=True)
    rows = [swap_log(1, 0, 2_000 * 10**6, -(10**18), 2001.0), swap_log(2, 0, 1, 0, 2001.0)]
    logs(rows).write_parquet(raw / "pool_logs_2026-07-01_2026-08-01.parquet")
    start = eth_price_to_sqrt_price_x96(2000.0)
    (raw / "snapshot_meta.json").write_text(
        json.dumps({"sqrt_price_x96": start, "fee_protocol": 0})
    )
    trades = "1,2500.5,0.1,1,1,1751328000123,True,True\n"
    klines = "1751328000000,1,2,0.5,1.5,10,1751328000999,15,3,5,7,0\n"
    for name, text in (
        ("ETHUSDC-aggTrades-2026-07.zip", trades),
        ("ETHUSDT-1s-2026-07.zip", klines),
    ):
        with zipfile.ZipFile(raw / "binance" / name, "w") as z:
            z.writestr("a.csv", text)
    build_all(raw, interim)
    for name, col in (("events", "sqrt_price_x96"), ("swaps", "fee_amount_raw")):
        schema = pq.read_schema(interim / f"{name}.parquet")  # fails on Polars' private Int128
        assert str(schema.field(col).type) == "decimal128(38, 0)"
    swaps = pq.read_table(interim / "swaps.parquet").to_pydict()
    assert [int(x) for x in swaps["fee_amount_raw"]] == [10**6, 1]
