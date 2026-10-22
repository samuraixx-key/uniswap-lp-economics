"""Builder revenue and payments in the window (spec D5), aggregated inside BigQuery (plan
Ruling 4): the window has ~110 M transactions, too many to download."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
from google.cloud import bigquery

from uniswap_lp_economics.config import GCP_PROJECT, POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS
from uniswap_lp_economics.data.bigquery import DATASET
from uniswap_lp_economics.data.blocks import _window
from uniswap_lp_economics.data.history import BILLING_HELP, is_billing_error
from uniswap_lp_economics.io import read_exact, write_exact
from uniswap_lp_economics.rpc import RpcClient

BUILDERS_DIR = "builders"
BLOCK_REVENUE = "block_revenue.parquet"
TX_DIRECT = "pool_tx_direct_payments.parquet"
TX_OTHER_LOGS = "pool_tx_other_logs.parquet"
LAST_TX = "last_tx.parquet"
PAYOUT_CODE = "payout_recipient_code.parquet"
MAX_GB_BILLED = 700


# A trace pays the fee recipient when it is a successful value transfer to it, from a
# transaction the fee recipient did not send (its own transactions, e.g. one unwrapping WETH,
# are excluded, spec 7) and not a delegate/static call (those carry no value of their own).
_TRACE_PAYMENT = """x.status = 1 AND x.value > 0
  AND x.to_address = b.miner AND t.from_address != b.miner
  AND (x.call_type IS NULL OR x.call_type NOT IN ('delegatecall', 'callcode', 'staticcall'))"""


def build_block_revenue_query(start: date, end: date) -> str:
    """Per block: priority fees (fee recipient's own transactions excluded), successful trace
    payments to the fee recipient, and the block's last transaction (the proposer payment)."""
    return f"""
WITH b AS (
  SELECT number, miner, base_fee_per_gas FROM `{DATASET}.blocks`
  WHERE {_window("timestamp", start, end)}
),
t AS (
  SELECT `hash`, block_number, transaction_index, from_address, value, receipt_gas_used,
         receipt_effective_gas_price
  FROM `{DATASET}.transactions` WHERE {_window("block_timestamp", start, end)}
),
pr AS (
  SELECT t.block_number,
         SUM(IF(t.from_address != b.miner,
                CAST(t.receipt_gas_used AS BIGNUMERIC)
                * (t.receipt_effective_gas_price - b.base_fee_per_gas), 0)) AS priority_wei,
         MAX(t.transaction_index) AS last_index
  FROM t JOIN b ON b.number = t.block_number
  GROUP BY t.block_number
),
tr AS (
  SELECT x.block_number, SUM(x.value) AS direct_wei
  FROM `{DATASET}.traces` x
  JOIN b ON b.number = x.block_number
  JOIN t ON t.`hash` = x.transaction_hash
  WHERE {_window("x.block_timestamp", start, end)} AND {_TRACE_PAYMENT}
  GROUP BY x.block_number
),
last AS (
  SELECT t.block_number, t.from_address AS last_from, t.value AS last_value
  FROM t JOIN pr ON pr.block_number = t.block_number AND pr.last_index = t.transaction_index
)
SELECT b.number AS block_number, b.miner,
       CAST(pr.priority_wei AS STRING) AS priority_wei,
       CAST(tr.direct_wei AS STRING) AS direct_wei,
       last.last_from, CAST(last.last_value AS STRING) AS last_value_wei
FROM b
LEFT JOIN pr ON pr.block_number = b.number
LEFT JOIN tr ON tr.block_number = b.number
LEFT JOIN last ON last.block_number = b.number
ORDER BY block_number
"""


def _pool_txs(start: date, end: date) -> str:
    return f"""pool_txs AS (
  SELECT DISTINCT transaction_hash FROM `{DATASET}.logs`
  WHERE {_window("block_timestamp", start, end)} AND address = '{POOL_ADDRESS}'
)"""


def build_tx_direct_query(start: date, end: date) -> str:
    """Per transaction touching our pool: successful trace payments to the block's fee recipient
    (same rule as the per-block table, so the two reconcile)."""
    return f"""
WITH {_pool_txs(start, end)},
b AS (SELECT number, miner FROM `{DATASET}.blocks` WHERE {_window("timestamp", start, end)}),
t AS (SELECT `hash`, from_address FROM `{DATASET}.transactions`
      WHERE {_window("block_timestamp", start, end)})
SELECT x.transaction_hash AS tx_hash, CAST(SUM(x.value) AS STRING) AS direct_wei
FROM `{DATASET}.traces` x
JOIN pool_txs p ON p.transaction_hash = x.transaction_hash
JOIN b ON b.number = x.block_number
JOIN t ON t.`hash` = x.transaction_hash
WHERE {_window("x.block_timestamp", start, end)} AND {_TRACE_PAYMENT}
GROUP BY x.transaction_hash
"""


def build_tx_other_logs_query(start: date, end: date) -> str:
    """Per transaction touching our pool: logs from anything other than our pool, USDC, WETH
    or the transaction's target (the created contract for a creation); non-zero means the
    transaction also traded elsewhere."""
    allowed = ", ".join(f"'{a}'" for a in (POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS))
    return f"""
WITH {_pool_txs(start, end)},
t AS (SELECT `hash`, COALESCE(to_address, receipt_contract_address) AS target
      FROM `{DATASET}.transactions` WHERE {_window("block_timestamp", start, end)})
SELECT l.transaction_hash AS tx_hash,
       COUNTIF(l.address NOT IN ({allowed}) AND l.address != t.target) AS other_logs,
       COUNT(*) AS logs
FROM `{DATASET}.logs` l
JOIN pool_txs p ON p.transaction_hash = l.transaction_hash
JOIN t ON t.`hash` = l.transaction_hash
WHERE {_window("l.block_timestamp", start, end)}
GROUP BY l.transaction_hash
"""


def build_last_tx_query(start: date, end: date) -> str:
    """Each block's last transaction: where it went and its gas. No calldata is read."""
    return f"""
SELECT block_number, to_address, receipt_gas_used FROM `{DATASET}.transactions`
WHERE {_window("block_timestamp", start, end)}
QUALIFY transaction_index = MAX(transaction_index) OVER (PARTITION BY block_number)
"""


def wei_columns(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    """Decimal strings from BigQuery (NUMERIC/BIGNUMERIC) to exact Int128; nulls become 0."""
    return df.with_columns(
        pl.Series(
            c,
            [int(Decimal(v)) if v is not None else 0 for v in df[c].to_list()],
            dtype=pl.Int128,
        )
        for c in cols
    )


def _run(client: bigquery.Client, query: str, dry_run: bool) -> pl.DataFrame | None:
    # A dry-run job is free: it only reports the bytes the paid query would scan.
    dry = client.query(query, job_config=bigquery.QueryJobConfig(dry_run=True))
    gb = (dry.total_bytes_processed or 0) / 1e9
    print(f"  scans {gb:.1f} GB")
    if gb > MAX_GB_BILLED:
        message = f"this query would scan {gb:.0f} GB, over the {MAX_GB_BILLED} GB cap"
        if not dry_run:
            raise SystemExit(f"{message}; nothing was billed")
        print(f"  WARNING: {message}; the paid run would refuse it")
    if dry_run:
        return None
    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=int(MAX_GB_BILLED * 1e9))
    df = pl.from_arrow(client.query(query, job_config=cfg).result().to_arrow())
    assert isinstance(df, pl.DataFrame)
    return df


def fetch_builders(
    raw_dir: Path, start: date, end: date, dry_run: bool = False, confirm_cost: bool = False
) -> None:
    """Download the four aggregated tables; files that exist are skipped. The queries are billed
    (about 676 GB together), so a real run with a table missing needs `confirm_cost`; a dry run
    (free: it only reports the bytes each query would scan) does not."""
    out = raw_dir / BUILDERS_DIR
    names = (BLOCK_REVENUE, TX_DIRECT, TX_OTHER_LOGS, LAST_TX)
    if not (dry_run or confirm_cost) and not all((out / n).exists() for n in names):
        raise SystemExit(
            "this is a paid BigQuery query; check its size with `ulpe fetch-builders --dry-run`, "
            "then run `ulpe fetch-builders --confirm-cost`"
        )
    out.mkdir(parents=True, exist_ok=True)
    client = bigquery.Client(project=GCP_PROJECT)
    jobs: list[tuple[str, str, list[str], dict[str, Any]]] = [
        (
            BLOCK_REVENUE,
            build_block_revenue_query(start, end),
            ["priority_wei", "direct_wei", "last_value_wei"],
            {"block_number": pl.Int64},
        ),
        (TX_DIRECT, build_tx_direct_query(start, end), ["direct_wei"], {}),
        (
            TX_OTHER_LOGS,
            build_tx_other_logs_query(start, end),
            [],
            {"other_logs": pl.Int64, "logs": pl.Int64},
        ),
        (
            LAST_TX,
            build_last_tx_query(start, end),
            [],
            {"block_number": pl.Int64, "receipt_gas_used": pl.Int64},
        ),
    ]
    for name, query, wei, casts in jobs:
        if not dry_run and (out / name).exists():
            print(f"{name} already downloaded, skipping")
            continue
        print(f"{name}:")
        try:
            df = _run(client, query, dry_run)
        except Exception as e:
            if is_billing_error(e):
                raise SystemExit(BILLING_HELP) from None
            raise
        if df is None:
            continue
        df = wei_columns(df, wei).with_columns(pl.col(c).cast(t) for c, t in casts.items())
        write_exact(df, out / name)
        print(f"  wrote {df.height:,} rows")


def load_builders(raw_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """(block_revenue, pool_tx_direct_payments, pool_tx_other_logs)."""
    folder = raw_dir / BUILDERS_DIR
    for name in (BLOCK_REVENUE, TX_DIRECT, TX_OTHER_LOGS):
        if not (folder / name).exists():
            raise FileNotFoundError(f"{folder / name} missing; run `ulpe fetch-builders` first")
    return (
        read_exact(folder / BLOCK_REVENUE),
        read_exact(folder / TX_DIRECT),
        read_exact(folder / TX_OTHER_LOGS),
    )


def load_last_tx(raw_dir: Path) -> pl.DataFrame:
    """(block_number, to_address, receipt_gas_used) of each block's last transaction."""
    path = raw_dir / BUILDERS_DIR / LAST_TX
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `ulpe fetch-builders` first")
    return read_exact(path)


def fetch_payout_code(client: RpcClient, raw_dir: Path, reads: list[tuple[str, int]]) -> Path:
    """`eth_getCode` of each (address, block) read; cached, so reruns read only missing pairs."""
    out = raw_dir / BUILDERS_DIR / PAYOUT_CODE
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = {"address": pl.String, "block": pl.Int64, "code": pl.String}
    known = pl.read_parquet(out) if out.exists() else pl.DataFrame(schema=schema)
    done = set(zip(known["address"].to_list(), known["block"].to_list(), strict=True))
    todo = [r for r in sorted(set(reads)) if r not in done]
    rows = []
    for i, (address, block) in enumerate(todo):
        rows.append({"address": address, "block": block, "code": client.get_code(address, block)})
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(todo)} payout recipient reads")
    write_exact(pl.concat([known, pl.DataFrame(rows, schema=schema)]), out)
    return out
