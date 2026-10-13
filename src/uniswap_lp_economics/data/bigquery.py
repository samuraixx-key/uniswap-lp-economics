"""Download raw pool logs (with tx sender/receiver and gas) from BigQuery's public Ethereum data."""

from datetime import date
from pathlib import Path

import polars as pl
from google.cloud import bigquery

from uniswap_lp_economics.config import DATA_DIR, GCP_PROJECT, POOL_ADDRESS

DATASET = "bigquery-public-data.crypto_ethereum"
MAX_GB_BILLED = 150  # hard cap per query; the sandbox gives 1 TB/month


def build_pool_logs_query(start: date, end: date) -> str:
    """All pool logs in [start, end), joined with their transaction's from/to and gas fields."""
    window = (
        f"block_timestamp >= TIMESTAMP('{start.isoformat()}') "
        f"AND block_timestamp < TIMESTAMP('{end.isoformat()}')"
    )
    return f"""
WITH pool_logs AS (
  SELECT block_number, block_timestamp, transaction_hash, transaction_index, log_index,
         topics, data
  FROM `{DATASET}.logs`
  WHERE {window} AND address = '{POOL_ADDRESS}'
),
txs AS (
  SELECT `hash`, from_address, to_address, receipt_gas_used, receipt_effective_gas_price,
         max_priority_fee_per_gas
  FROM `{DATASET}.transactions`
  WHERE {window}
)
SELECT l.*, t.from_address, t.to_address, t.receipt_gas_used, t.receipt_effective_gas_price,
       t.max_priority_fee_per_gas
FROM pool_logs l
LEFT JOIN txs t ON t.`hash` = l.transaction_hash
ORDER BY l.block_number, l.log_index
"""


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end) into calendar-month chunks."""
    windows = []
    cur = start
    while cur < end:
        nxt = date(cur.year + cur.month // 12, cur.month % 12 + 1, 1)
        windows.append((cur, min(nxt, end)))
        cur = nxt
    return windows


def raw_logs_path(start: date, end: date) -> Path:
    return DATA_DIR / "raw" / f"pool_logs_{start.isoformat()}_{end.isoformat()}.parquet"


def fetch_pool_logs(start: date, end: date, dry_run: bool = False) -> Path | None:
    """Download one window to parquet. With dry_run, only print the bytes it would scan."""
    client = bigquery.Client(project=GCP_PROJECT)
    query = build_pool_logs_query(start, end)
    dry = client.query(query, job_config=bigquery.QueryJobConfig(dry_run=True))
    gb = (dry.total_bytes_processed or 0) / 1e9
    print(f"{start} -> {end}: scans {gb:.1f} GB")
    if dry_run:
        return None

    config = bigquery.QueryJobConfig(maximum_bytes_billed=int(MAX_GB_BILLED * 1e9))
    table = client.query(query, job_config=config).result().to_arrow()
    df = pl.from_arrow(table)
    assert isinstance(df, pl.DataFrame)
    out = raw_logs_path(start, end)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)
    print(f"  wrote {df.height:,} logs to {out}")
    return out
