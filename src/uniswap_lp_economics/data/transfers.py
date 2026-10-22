"""Internal ETH transfers sent by the top bot contracts, via Alchemy's alchemy_getAssetTransfers.

A direct builder payment (block.coinbase.transfer) shows up as an internal transfer from the bot
contract to the block's fee recipient; arbprofit.py does that matching.
"""

from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics.io import read_exact, write_exact
from uniswap_lp_economics.rpc import RpcClient

TRANSFER_SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "tx_hash": pl.String,
    "from_address": pl.String,
    "to_address": pl.String,
    "value_wei": pl.Int128,
}
PAGE_SIZE = 1000
TRANSFERS_DIR = "bot_transfers"


def fetch_internal_transfers(
    client: RpcClient, address: str, from_block: int, to_block: int
) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    page_key: str | None = None
    while True:
        params: dict[str, Any] = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "fromAddress": address,
            "category": ["internal"],
            "excludeZeroValue": True,
            "withMetadata": False,
            "maxCount": hex(PAGE_SIZE),
        }
        if page_key:
            params["pageKey"] = page_key
        result = client.request("alchemy_getAssetTransfers", [params])
        for t in result["transfers"]:
            raw_value = (t.get("rawContract") or {}).get("value")
            if raw_value is None:
                raise ValueError(f"transfer {t.get('uniqueId')} has no rawContract.value")
            rows.append(
                {
                    "block_number": int(t["blockNum"], 16),
                    "tx_hash": t["hash"].lower(),
                    "from_address": t["from"].lower(),
                    "to_address": (t["to"] or "").lower(),
                    "value_wei": int(raw_value, 16),
                }
            )
        page_key = result.get("pageKey")
        if not page_key:
            return pl.DataFrame(rows, schema=TRANSFER_SCHEMA)


def fetch_bot_transfers(
    client: RpcClient, raw_dir: Path, bots: list[str], from_block: int, to_block: int
) -> None:
    """Fetch each bot's transfers once; a contract whose file exists is skipped."""
    out_dir = raw_dir / TRANSFERS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, bot in enumerate(bots, start=1):
        out = out_dir / f"{bot}.parquet"
        if out.exists():
            print(f"  {i}/{len(bots)} {bot}: cached")
            continue
        df = fetch_internal_transfers(client, bot, from_block, to_block)
        write_exact(df, out)
        print(f"  {i}/{len(bots)} {bot}: {df.height:,} transfers")


def load_bot_transfers(raw_dir: Path, bots: list[str]) -> pl.DataFrame:
    """Transfers for exactly these bots; FileNotFoundError if any bot was never fetched."""
    out_dir = raw_dir / TRANSFERS_DIR
    missing = [b for b in bots if not (out_dir / f"{b}.parquet").exists()]
    if missing:
        raise FileNotFoundError(
            f"no transfer data for {len(missing)} top bot(s), e.g. {missing[0]}; "
            "run `ulpe fetch-transfers`"
        )
    frames = [read_exact(out_dir / f"{b}.parquet") for b in bots]
    if not frames:
        return pl.DataFrame(schema=TRANSFER_SCHEMA)
    return pl.concat(frames)


# Payment paths through forwarding contracts for the seed-45 holdout (forwarder spec section 4).
PATHS_FILE = "holdout2_paths.parquet"
PATH_SCHEMA: dict[str, Any] = {"block_number": pl.Int64, "tx_hash": pl.String, "path": pl.String}
MAX_HOPS = 3
PATH_CHECKPOINT = 50


def payment_path(
    client: RpcClient, block: int, to_address: str, value_wei: int
) -> tuple[str, list[str]]:
    """(hash of the block's last transaction, payment path). The path starts at `to_address` and
    follows, at most MAX_HOPS times, the one internal transfer sent by the current address in
    that transaction with value >= `value_wei`; it stops when there is not exactly one, or when
    the recipient is already on the path. Raises if the RPC's last transaction does not go to
    `to_address` with `value_wei` (the chain tables and the node disagree)."""
    last = client.request("eth_getBlockByNumber", [hex(block), True])["transactions"][-1]
    if (last["to"] or "").lower() != to_address.lower() or int(last["value"], 16) != value_wei:
        raise ValueError(f"block {block}: last transaction does not match the chain tables")
    tx = last["hash"].lower()
    path = [to_address.lower()]
    for _ in range(MAX_HOPS):
        out = fetch_internal_transfers(client, path[-1], block, block).filter(
            (pl.col("tx_hash") == tx) & (pl.col("value_wei") >= value_wei)
        )
        if out.height != 1 or out["to_address"][0] in path:
            break
        path.append(out["to_address"][0])
    return tx, path


def fetch_payment_paths(client: RpcClient, raw_dir: Path, targets: pl.DataFrame) -> Path:
    """Payment paths of `targets` (block_number, to_address, last_value_wei) into PATHS_FILE;
    blocks already there are skipped. Saved every PATH_CHECKPOINT blocks and on any exit, so an
    error keeps the rows fetched before it."""
    out = raw_dir / PATHS_FILE
    done = read_exact(out) if out.exists() else pl.DataFrame(schema=PATH_SCHEMA)
    have = set(done["block_number"].to_list())
    todo = targets.filter(~pl.col("block_number").is_in(list(have))).sort("block_number")
    rows: list[dict[str, Any]] = []

    def save() -> None:
        write_exact(pl.concat([done, pl.DataFrame(rows, schema=PATH_SCHEMA)]), out)

    try:
        for i, (b, to, v) in enumerate(
            todo.select("block_number", "to_address", "last_value_wei").iter_rows()
        ):
            tx, path = payment_path(client, b, to, v)
            rows.append({"block_number": b, "tx_hash": tx, "path": ",".join(path)})
            if (i + 1) % PATH_CHECKPOINT == 0:
                save()
                print(f"  {i + 1}/{todo.height} payment paths")
    finally:
        if rows:
            save()
    print(f"  payment paths: {len(rows)} fetched, {len(have) + len(rows)} on disk")
    return out
