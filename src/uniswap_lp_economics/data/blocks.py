"""BigQuery fetches for sub-project 2: block metadata, and the logs inside top-bot transactions."""

import json
import re
from datetime import date
from pathlib import Path

import polars as pl
from google.cloud import bigquery

from uniswap_lp_economics.config import GCP_PROJECT, POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS
from uniswap_lp_economics.data.bigquery import DATASET, MAX_GB_BILLED

_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
BLOCKS_FILE = "blocks.parquet"
OTHER_LOGS_FILE = "bot_tx_other_logs.parquet"
OTHER_LOGS_META = "bot_tx_other_logs.json"


def _window(column: str, start: date, end: date) -> str:
    return (
        f"{column} >= TIMESTAMP('{start.isoformat()}') "
        f"AND {column} < TIMESTAMP('{end.isoformat()}')"
    )


def build_blocks_query(start: date, end: date) -> str:
    return f"""
SELECT number AS block_number, timestamp AS block_timestamp, miner, base_fee_per_gas
FROM `{DATASET}.blocks`
WHERE {_window("timestamp", start, end)}
ORDER BY number
"""


def build_other_logs_query(start: date, end: date, bots: list[str]) -> str:
    """Per transaction sent to a top bot: logs emitted by anything other than our pool, USDC,
    WETH or the bot itself (non-zero means the transaction also traded elsewhere)."""
    if not bots:
        raise ValueError("no bot addresses given")
    for b in bots:
        if not _ADDRESS.match(b):
            raise ValueError(f"bot address {b!r} must be 0x + 40 lowercase hex")
    listed = ", ".join(f"'{b}'" for b in bots)
    allowed = ", ".join(f"'{a}'" for a in (POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS))
    return f"""
WITH bot_txs AS (
  SELECT `hash` AS tx_hash, to_address
  FROM `{DATASET}.transactions`
  WHERE {_window("block_timestamp", start, end)} AND to_address IN ({listed})
)
SELECT b.tx_hash, b.to_address AS bot,
       COUNTIF(l.address NOT IN ({allowed}) AND l.address != b.to_address) AS other_logs,
       COUNT(*) AS logs
FROM bot_txs b
JOIN `{DATASET}.logs` l ON l.transaction_hash = b.tx_hash
WHERE {_window("l.block_timestamp", start, end)}
GROUP BY b.tx_hash, b.to_address
"""


def _run(query: str, dry_run: bool) -> pl.DataFrame | None:
    client = bigquery.Client(project=GCP_PROJECT)
    dry = client.query(query, job_config=bigquery.QueryJobConfig(dry_run=True))
    print(f"  scans {(dry.total_bytes_processed or 0) / 1e9:.1f} GB")
    if dry_run:
        return None
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=int(MAX_GB_BILLED * 1e9))
    df = pl.from_arrow(client.query(query, job_config=job_config).result().to_arrow())
    assert isinstance(df, pl.DataFrame)
    return df


def _write(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    df.write_parquet(part)
    part.replace(path)


def fetch_blocks(raw_dir: Path, start: date, end: date, dry_run: bool = False) -> Path | None:
    print(f"blocks {start} -> {end}:")
    df = _run(build_blocks_query(start, end), dry_run)
    if df is None:
        return None
    df = df.with_columns(
        pl.col("block_number").cast(pl.Int64),
        pl.col("block_timestamp").cast(pl.Datetime("us", "UTC")),
        pl.col("base_fee_per_gas").cast(pl.Int64),
    )
    out = raw_dir / BLOCKS_FILE
    _write(df, out)
    print(f"  wrote {df.height:,} blocks to {out}")
    return out


def fetch_bot_tx_logs(
    raw_dir: Path, start: date, end: date, bots: list[str], dry_run: bool = False
) -> Path | None:
    print(f"other logs in transactions to {len(bots)} top bots, {start} -> {end}:")
    df = _run(build_other_logs_query(start, end, bots), dry_run)
    if df is None:
        return None
    df = df.with_columns(pl.col("other_logs").cast(pl.Int64), pl.col("logs").cast(pl.Int64))
    out = raw_dir / OTHER_LOGS_FILE
    _write(df, out)
    # The bot list is the freshness marker, so it is written last.
    meta = raw_dir / OTHER_LOGS_META
    part = meta.with_name(meta.name + ".part")
    part.write_text(json.dumps({"bots": sorted(bots)}, indent=2))
    part.replace(meta)
    print(f"  wrote {df.height:,} transactions to {out}")
    return out


def bot_tx_logs_current(raw_dir: Path, bots: list[str]) -> bool:
    """True when the other-log data on disk was fetched for (at least) these bots."""
    meta = raw_dir / OTHER_LOGS_META
    if not meta.exists() or not (raw_dir / OTHER_LOGS_FILE).exists():
        return False
    fetched = set(json.loads(meta.read_text())["bots"])
    return set(bots) <= fetched
