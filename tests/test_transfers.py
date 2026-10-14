import json
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest

from uniswap_lp_economics.data.transfers import (
    fetch_bot_transfers,
    fetch_internal_transfers,
    load_bot_transfers,
)
from uniswap_lp_economics.rpc import RpcClient

URL = "https://example.invalid/v2/SECRETKEY"
BOT = "0x" + "b0" * 20
BOT2 = "0x" + "b1" * 20
MINER = "0x" + "ee" * 20


def transfer(block: int, tx: str, frm: str, to: str, wei: int) -> dict[str, Any]:
    return {
        "blockNum": hex(block),
        "hash": tx,
        "from": frm,
        "to": to,
        "value": wei / 1e18,
        "rawContract": {"value": hex(wei), "address": None, "decimal": "0x12"},
        "category": "internal",
        "uniqueId": f"{tx}:internal:0",
    }


def fake(pages: list[dict[str, Any]]) -> tuple[RpcClient, list[dict[str, Any]]]:
    """A client whose n-th request gets pages[n]; the request params are recorded."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["params"][0])
        result = pages[len(seen) - 1]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    return RpcClient(URL, transport=httpx.MockTransport(handler), backoff_s=0), seen


def test_fetch_internal_transfers_follows_page_keys() -> None:
    client, seen = fake(
        [
            {"transfers": [transfer(10, "0xAA", BOT.upper(), MINER, 5)], "pageKey": "k1"},
            {"transfers": [transfer(11, "0xbb", BOT, MINER, 2**70)]},
        ]
    )
    df = fetch_internal_transfers(client, BOT, 1, 20)
    assert df["value_wei"].to_list() == [5, 2**70]
    assert df["tx_hash"].to_list() == ["0xaa", "0xbb"]
    assert df["from_address"].to_list() == [BOT, BOT]
    assert df["block_number"].to_list() == [10, 11]
    assert seen[0]["category"] == ["internal"]
    assert seen[0]["fromAddress"] == BOT and seen[0]["fromBlock"] == hex(1)
    assert seen[0]["toBlock"] == hex(20)
    assert "pageKey" not in seen[0] and seen[1]["pageKey"] == "k1"


def test_fetch_bot_transfers_caches_per_contract(tmp_path: Path) -> None:
    client, seen = fake([{"transfers": [transfer(10, "0x01", BOT, MINER, 7)]}, {"transfers": []}])
    fetch_bot_transfers(client, tmp_path, [BOT, BOT2], 1, 20)
    assert len(seen) == 2
    fetch_bot_transfers(client, tmp_path, [BOT, BOT2], 1, 20)  # all cached: no requests
    assert len(seen) == 2
    df = load_bot_transfers(tmp_path, [BOT, BOT2])
    assert df["value_wei"].to_list() == [7]
    assert df.schema["value_wei"] == pl.Int128


def test_load_bot_transfers_names_missing_bots(tmp_path: Path) -> None:
    client, _ = fake([{"transfers": []}])
    fetch_bot_transfers(client, tmp_path, [BOT], 1, 20)
    with pytest.raises(FileNotFoundError, match="ulpe fetch-transfers"):
        load_bot_transfers(tmp_path, [BOT, BOT2])


@pytest.mark.live
def test_live_internal_transfers_from_weth() -> None:
    from uniswap_lp_economics import config

    assert config.ETH_RPC_URL
    client = RpcClient(config.ETH_RPC_URL)
    df = fetch_internal_transfers(client, config.WETH_ADDRESS, 25_433_939, 25_433_941)
    assert set(df.columns) == {"block_number", "tx_hash", "from_address", "to_address", "value_wei"}
