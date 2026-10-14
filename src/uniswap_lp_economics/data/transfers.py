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
