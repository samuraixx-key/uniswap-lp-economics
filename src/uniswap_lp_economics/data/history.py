"""Full pool and NonfungiblePositionManager history (spec D1, section 3.2).

Stage 1 is the one paid query: every pool Mint/Burn/Collect and every NPM IncreaseLiquidity/
DecreaseLiquidity/Collect/Transfer since the pool was created, written into a table in the user's
project. Stage 2 queries only that table (cents): the pool's events, and the NPM events of tokens
minted into our pool. Stage 1 never runs without --confirm-cost (the user confirms in chat first).
"""

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from uniswap_lp_economics.abi import enc_addr, to_addr, to_uint, topic, words
from uniswap_lp_economics.build import decode_logs
from uniswap_lp_economics.config import GCP_PROJECT, NPM_ADDRESS, POOL_ADDRESS
from uniswap_lp_economics.data.bigquery import DATASET
from uniswap_lp_economics.events import BURN_TOPIC, COLLECT_TOPIC, MINT_TOPIC
from uniswap_lp_economics.io import write_exact

HISTORY_DIR = "history"
POOL_FILE = "pool_events.parquet"
NPM_FILE = "npm_events.parquet"
BQ_DATASET = "ulpe_history"
BQ_TABLE = "logs"
MAX_TB_BILLED = 3.1
STAGE2_MAX_GB_BILLED = 200
TABLE_EXPIRATION_MS = 7 * 24 * 3600 * 1000

INCREASE_TOPIC = topic("IncreaseLiquidity(uint256,uint128,uint256,uint256)")
DECREASE_TOPIC = topic("DecreaseLiquidity(uint256,uint128,uint256,uint256)")
NPM_COLLECT_TOPIC = topic("Collect(uint256,address,uint256,uint256)")
TRANSFER_TOPIC = topic("Transfer(address,address,uint256)")
NPM_TOPICS = {
    INCREASE_TOPIC: "increase",
    DECREASE_TOPIC: "decrease",
    NPM_COLLECT_TOPIC: "npm_collect",
    TRANSFER_TOPIC: "transfer",
}
_COLUMNS = (
    "block_number, block_timestamp, transaction_hash, transaction_index, log_index, "
    "address, topics, data"
)
BILLING_HELP = (
    "BigQuery refused the query: billing is not enabled for this project, or the free tier is "
    "used up. Link a billing account to the project (console.cloud.google.com/billing → "
    "Account management → Link a project) and run the command again."
)
NPM_SCHEMA: dict[str, Any] = {
    "event": pl.String,
    "token_id": pl.Int64,
    "liquidity": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
    "recipient": pl.String,
    "from_owner": pl.String,
    "to_owner": pl.String,
}


def table_id(project: str = GCP_PROJECT) -> str:
    return f"{project}.{BQ_DATASET}.{BQ_TABLE}"


def build_stage1_query(start: date, end: date) -> str:
    topics = ", ".join(f"'{t}'" for t in (MINT_TOPIC, BURN_TOPIC, COLLECT_TOPIC, *NPM_TOPICS))
    return f"""
SELECT {_COLUMNS}
FROM `{DATASET}.logs`
WHERE block_timestamp >= TIMESTAMP('{start.isoformat()}')
  AND block_timestamp < TIMESTAMP('{end.isoformat()}')
  AND address IN ('{POOL_ADDRESS}', '{NPM_ADDRESS}')
  AND topics[SAFE_OFFSET(0)] IN ({topics})
"""


def build_pool_query(table: str) -> str:
    return f"""
SELECT {_COLUMNS} FROM `{table}`
WHERE address = '{POOL_ADDRESS}'
ORDER BY block_number, log_index
"""


def build_npm_query(table: str) -> str:
    """NPM events of every token whose IncreaseLiquidity shares a transaction with a pool Mint
    owned by the position manager. A token of another pool minted in the same transaction can
    slip in; lp.positions ignores it (its events never match a pool event)."""
    npm_owner = "0x" + enc_addr(NPM_ADDRESS)
    return f"""
WITH ours AS (
  SELECT DISTINCT n.topics[SAFE_OFFSET(1)] AS token
  FROM `{table}` n
  JOIN `{table}` p ON p.transaction_hash = n.transaction_hash
  WHERE n.address = '{NPM_ADDRESS}' AND n.topics[SAFE_OFFSET(0)] = '{INCREASE_TOPIC}'
    AND p.address = '{POOL_ADDRESS}' AND p.topics[SAFE_OFFSET(0)] = '{MINT_TOPIC}'
    AND p.topics[SAFE_OFFSET(1)] = '{npm_owner}'
)
SELECT {_COLUMNS} FROM `{table}` t
WHERE t.address = '{NPM_ADDRESS}' AND (
  (t.topics[SAFE_OFFSET(0)] IN ('{INCREASE_TOPIC}', '{DECREASE_TOPIC}', '{NPM_COLLECT_TOPIC}')
   AND t.topics[SAFE_OFFSET(1)] IN (SELECT token FROM ours))
  OR (t.topics[SAFE_OFFSET(0)] = '{TRANSFER_TOPIC}'
   AND t.topics[SAFE_OFFSET(3)] IN (SELECT token FROM ours))
)
ORDER BY block_number, log_index
"""


def stage1_action(table_exists: bool, dry_run: bool, confirm_cost: bool) -> str:
    """What fetch_history may do. Every billable query needs --confirm-cost (stage 2 too), and a
    dry run never bills, whatever the table state. "skip" means: stage 1 exists, run stage 2."""
    if dry_run:
        return "dry_run"
    if not confirm_cost:
        return "refuse"
    return "skip" if table_exists else "run"


def is_billing_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(s in text for s in ("billing", "free query bytes", "sandbox"))


def fetch_history(
    raw_dir: Path, start: date, end: date, confirm_cost: bool, dry_run: bool = False
) -> None:
    out = raw_dir / HISTORY_DIR
    if not dry_run and (out / POOL_FILE).exists() and (out / NPM_FILE).exists():
        print("history already downloaded, skipping")
        return
    client = bigquery.Client(project=GCP_PROJECT)
    tid = table_id()
    try:
        client.get_table(tid)
        exists = True
    except NotFound:
        exists = False
    query = build_stage1_query(start, end)
    action = stage1_action(exists, dry_run, confirm_cost)
    if exists:
        print(
            f"stage-1 table {tid} exists; stage 2 would query it "
            f"(capped at {STAGE2_MAX_GB_BILLED} GB billed)"
        )
    else:
        # A dry-run job is free: it only reports the bytes the paid query would scan.
        dry = client.query(query, job_config=bigquery.QueryJobConfig(dry_run=True))
        tb = (dry.total_bytes_processed or 0) / 1e12
        print(f"stage 1 ({start} -> {end}) scans {tb:.2f} TB; it is billed to the project")
    if action == "dry_run":
        return
    if action == "refuse":
        raise SystemExit(
            "this is a paid BigQuery query; after confirming the cost, run "
            "`ulpe fetch-history --confirm-cost`"
        )
    try:
        if action == "run":
            ds = bigquery.Dataset(f"{GCP_PROJECT}.{BQ_DATASET}")
            ds.location = "US"
            ds.default_table_expiration_ms = TABLE_EXPIRATION_MS
            client.create_dataset(ds, exists_ok=True)
            cfg = bigquery.QueryJobConfig(
                destination=tid,
                write_disposition="WRITE_TRUNCATE",
                maximum_bytes_billed=int(MAX_TB_BILLED * 1e12),
            )
            client.query(query, job_config=cfg).result()
            print(f"  stage 1 written to {tid}")
        out.mkdir(parents=True, exist_ok=True)
        # The pool file is the skip marker, so it is written last.
        for name, q in ((NPM_FILE, build_npm_query(tid)), (POOL_FILE, build_pool_query(tid))):
            cfg2 = bigquery.QueryJobConfig(maximum_bytes_billed=int(STAGE2_MAX_GB_BILLED * 1e9))
            df = pl.from_arrow(client.query(q, job_config=cfg2).result().to_arrow())
            assert isinstance(df, pl.DataFrame)
            write_exact(df, out / name)
            print(f"  wrote {df.height:,} rows to {out / name}")
    except Exception as e:
        if is_billing_error(e):
            raise SystemExit(BILLING_HELP) from None
        raise


def decode_npm_event(topics: list[str], data: str) -> dict[str, Any]:
    kind = NPM_TOPICS.get(topics[0].lower())
    if kind is None:
        raise ValueError(f"unknown NonfungiblePositionManager topic {topics[0]}")
    t = [words(x)[0] for x in topics[1:]]
    d = words(data) if data and data != "0x" else []
    if kind == "transfer":
        return {
            "event": kind,
            "from_owner": to_addr(t[0]),
            "to_owner": to_addr(t[1]),
            "token_id": to_uint(t[2]),
        }
    if kind == "npm_collect":
        return {
            "event": kind,
            "token_id": to_uint(t[0]),
            "recipient": to_addr(d[0]),
            "amount0": to_uint(d[1]),
            "amount1": to_uint(d[2]),
        }
    return {
        "event": kind,
        "token_id": to_uint(t[0]),
        "liquidity": to_uint(d[0]),
        "amount0": to_uint(d[1]),
        "amount1": to_uint(d[2]),
    }


def decode_npm_logs(raw: pl.DataFrame) -> pl.DataFrame:
    rows = [
        decode_npm_event(t, d)
        for t, d in zip(raw["topics"].to_list(), raw["data"].to_list(), strict=True)
    ]
    decoded = pl.from_dicts(rows, schema=NPM_SCHEMA)
    base = raw.select(
        pl.col("block_number").cast(pl.Int64),
        pl.col("block_timestamp").cast(pl.Datetime("us", "UTC")),
        pl.col("transaction_hash").alias("tx_hash"),
        pl.col("transaction_index").cast(pl.Int64),
        pl.col("log_index").cast(pl.Int64),
    )
    return pl.concat([base, decoded], how="horizontal").sort("block_number", "log_index")


def load_history(raw_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    folder = raw_dir / HISTORY_DIR
    for name in (POOL_FILE, NPM_FILE):
        if not (folder / name).exists():
            raise FileNotFoundError(f"{folder / name} missing; run `ulpe fetch-history` first")
    pool = decode_logs(pl.read_parquet(folder / POOL_FILE)).with_columns(
        pl.col("block_number").cast(pl.Int64),
        pl.col("log_index").cast(pl.Int64),
        pl.col("block_timestamp").cast(pl.Datetime("us", "UTC")),
    )
    npm = decode_npm_logs(pl.read_parquet(folder / NPM_FILE))
    return pool.sort("block_number", "log_index"), npm
