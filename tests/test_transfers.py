import json
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest

from uniswap_lp_economics.data.transfers import (
    PATH_SCHEMA,
    PATHS_FILE,
    fetch_bot_transfers,
    fetch_internal_transfers,
    fetch_payment_paths,
    load_bot_transfers,
    payment_path,
)
from uniswap_lp_economics.io import read_exact
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


FWD, PROP, FEE, OTHER = ("0x" + h * 20 for h in ("fe", "a1", "a2", "a3"))
TX, TX2 = "0x" + "11" * 32, "0x" + "22" * 32


def chain(
    last: dict[str, Any], transfers: dict[str, list[dict[str, Any]]]
) -> tuple[RpcClient, list[str]]:
    """A client for one block: eth_getBlockByNumber returns a block ending in `last`;
    alchemy_getAssetTransfers returns `transfers[fromAddress]`. Methods called are recorded."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["method"])
        if body["method"] == "eth_getBlockByNumber":
            result: Any = {"transactions": [{"hash": TX2, "to": OTHER, "value": "0x1"}, last]}
        else:
            result = {"transfers": transfers.get(body["params"][0]["fromAddress"], [])}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    return RpcClient(URL, transport=httpx.MockTransport(handler), backoff_s=0), calls


def last_tx(to: str, wei: int) -> dict[str, Any]:
    return {"hash": TX, "to": to.upper().replace("0X", "0x"), "value": hex(wei)}


def test_a_forwarder_hop_reaches_the_proposer() -> None:
    client, _ = chain(last_tx(FWD, 100), {FWD: [transfer(9, TX, FWD, PROP, 100)]})
    assert payment_path(client, 9, FWD, 100) == (TX, [FWD, PROP])


def test_two_hops_and_dust_are_followed() -> None:
    hops = {FWD: [transfer(9, TX, FWD, FEE, 101)], FEE: [transfer(9, TX, FEE, PROP, 101)]}
    client, _ = chain(last_tx(FWD, 100), hops)
    assert payment_path(client, 9, FWD, 100)[1] == [FWD, FEE, PROP]


def test_a_split_stops_the_path() -> None:
    split = [transfer(9, TX, FWD, PROP, 100), transfer(9, TX, FWD, FEE, 100)]
    client, _ = chain(last_tx(FWD, 100), {FWD: split})
    assert payment_path(client, 9, FWD, 100)[1] == [FWD]


def test_a_smaller_transfer_or_another_transaction_is_not_followed() -> None:
    other = [transfer(9, TX, FWD, PROP, 99), transfer(9, TX2, FWD, FEE, 500)]
    client, _ = chain(last_tx(FWD, 100), {FWD: other})
    assert payment_path(client, 9, FWD, 100)[1] == [FWD]


def test_a_loop_stops_and_a_fourth_hop_is_not_taken() -> None:
    loop = {FWD: [transfer(9, TX, FWD, FEE, 100)], FEE: [transfer(9, TX, FEE, FWD, 100)]}
    client, _ = chain(last_tx(FWD, 100), loop)
    assert payment_path(client, 9, FWD, 100)[1] == [FWD, FEE]
    a, b, c, d = ("0x" + h * 20 for h in ("b1", "b2", "b3", "b4"))
    long = {x: [transfer(9, TX, x, y, 100)] for x, y in ((FWD, a), (a, b), (b, c), (c, d))}
    client, calls = chain(last_tx(FWD, 100), long)
    assert payment_path(client, 9, FWD, 100)[1] == [FWD, a, b, c]
    assert calls.count("alchemy_getAssetTransfers") == 3


def test_a_last_tx_mismatch_raises_and_writes_nothing(tmp_path: Path) -> None:
    client, _ = chain(last_tx(OTHER, 100), {})
    targets = pl.DataFrame(
        {"block_number": [9], "to_address": [FWD], "last_value_wei": [100]},
        schema={"block_number": pl.Int64, "to_address": pl.String, "last_value_wei": pl.Int128},
    )
    with pytest.raises(ValueError, match="block 9"):
        fetch_payment_paths(client, tmp_path, targets)
    assert not (tmp_path / PATHS_FILE).exists()
    client, _ = chain(last_tx(FWD, 99), {})
    with pytest.raises(ValueError, match="block 9"):
        payment_path(client, 9, FWD, 100)


def test_paths_are_written_and_a_rerun_skips_done_blocks(tmp_path: Path) -> None:
    client, calls = chain(last_tx(FWD, 100), {FWD: [transfer(9, TX, FWD, PROP, 100)]})
    targets = pl.DataFrame(
        {"block_number": [9], "to_address": [FWD], "last_value_wei": [100]},
        schema={"block_number": pl.Int64, "to_address": pl.String, "last_value_wei": pl.Int128},
    )
    path = fetch_payment_paths(client, tmp_path, targets)
    df = read_exact(path)
    assert df.schema == pl.Schema(PATH_SCHEMA) and df.row(0) == (9, TX, f"{FWD},{PROP}")
    calls.clear()
    fetch_payment_paths(client, tmp_path, targets)
    assert calls == [] and read_exact(path).height == 1
