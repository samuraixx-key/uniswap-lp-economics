"""Command-line entry point: `uv run ulpe <command>`."""

import argparse
import json
from datetime import UTC, date, datetime

import polars as pl

from uniswap_lp_economics import config, snapshot
from uniswap_lp_economics.data import bigquery
from uniswap_lp_economics.rpc import RpcClient


def _rpc() -> RpcClient:
    if not config.ETH_RPC_URL:
        raise SystemExit("ETH_RPC_URL is not set in .env")
    return RpcClient(config.ETH_RPC_URL)


def _raw_logs() -> pl.DataFrame:
    files = sorted(config.RAW_DIR.glob("pool_logs_*.parquet"))
    if not files:
        raise SystemExit(f"no pool logs in {config.RAW_DIR}; run `ulpe fetch-logs` first")
    return pl.read_parquet(files)


def fetch_snapshot() -> None:
    meta_path = config.RAW_DIR / "snapshot_meta.json"
    if meta_path.exists():
        print("snapshot already downloaded, skipping")
        return
    client = _rpc()
    first_log_block = int(_raw_logs()["block_number"].min())  # type: ignore[arg-type]
    start_ts = int(datetime.combine(config.WINDOW_START, datetime.min.time(), UTC).timestamp())
    block = snapshot.find_last_block_before(
        client, start_ts, first_log_block - 2_000, first_log_block
    )
    ticks, meta = snapshot.read_tick_book(client, block)
    ticks.write_parquet(config.RAW_DIR / "tickbook_snapshot.parquet")
    meta["timestamp"] = client.block_timestamp(block)
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"snapshot at block {block}: {ticks.height} initialized ticks")


def fetch_samples() -> None:
    out = config.RAW_DIR / "onchain_samples.parquet"
    if out.exists():
        print("samples already downloaded, skipping")
        return
    client = _rpc()
    meta = json.loads((config.RAW_DIR / "snapshot_meta.json").read_text())
    last_block = int(_raw_logs()["block_number"].max())  # type: ignore[arg-type]
    blocks, full = snapshot.pick_sample_blocks(meta["block"] + 1, last_block)
    states, tick_frames = [], []
    for i, block in enumerate(blocks):
        if block in full:
            ticks, state = snapshot.read_tick_book(client, block)
        else:
            state, ticks = snapshot.read_sample(client, block)
        states.append({**state, "full_book": block in full})
        tick_frames.append(ticks.with_columns(block=pl.lit(block, dtype=pl.Int64)))
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(blocks)} samples")
    pl.DataFrame(
        states,
        schema={
            "block": pl.Int64,
            "sqrt_price_x96": pl.Int128,
            "tick": pl.Int64,
            "fee_protocol": pl.Int64,
            "liquidity": pl.Int128,
            "full_book": pl.Boolean,
        },
    ).write_parquet(out)
    pl.concat(tick_frames).write_parquet(config.RAW_DIR / "onchain_sample_ticks.parquet")
    print(f"wrote {len(blocks)} samples ({len(full)} full-book)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ulpe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch-logs", help="download pool logs from BigQuery, one file per month"
    )
    fetch.add_argument("--start", type=date.fromisoformat, required=True)
    fetch.add_argument("--end", type=date.fromisoformat, required=True, help="exclusive")
    fetch.add_argument("--dry-run", action="store_true", help="only report bytes scanned")
    sub.add_parser("fetch-snapshot", help="read the full tick book just before the window (RPC)")
    sub.add_parser("fetch-samples", help="read on-chain state at 500 random blocks (RPC)")

    args = parser.parse_args()
    if args.command == "fetch-logs":
        for start, end in bigquery.month_windows(args.start, args.end):
            if not args.dry_run and bigquery.raw_logs_path(start, end).exists():
                print(f"{start} -> {end}: already downloaded, skipping")
                continue
            bigquery.fetch_pool_logs(start, end, dry_run=args.dry_run)
    elif args.command == "fetch-snapshot":
        fetch_snapshot()
    elif args.command == "fetch-samples":
        fetch_samples()


if __name__ == "__main__":
    main()
