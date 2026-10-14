"""Command-line entry point: `uv run ulpe <command>`."""

import argparse
import json
from datetime import UTC, date, datetime

import polars as pl

from uniswap_lp_economics import analyze as analysis
from uniswap_lp_economics import build, config, flows, snapshot, validate
from uniswap_lp_economics.data import bigquery, binance, transfers
from uniswap_lp_economics.data import blocks as bq_blocks
from uniswap_lp_economics.io import read_exact, write_exact, write_text_atomic
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
    write_exact(ticks, config.RAW_DIR / "tickbook_snapshot.parquet")
    meta["timestamp"] = client.block_timestamp(block)
    # snapshot_meta.json is the skip marker, so it comes last and atomically.
    write_text_atomic(meta_path, json.dumps(meta, indent=2))
    print(f"snapshot at block {block}: {ticks.height} initialized ticks")


def fetch_samples() -> None:
    out = config.RAW_DIR / "onchain_samples.parquet"
    if out.exists():
        print("samples already downloaded, skipping")
        return
    meta_path = config.RAW_DIR / "snapshot_meta.json"
    if not meta_path.exists():
        raise SystemExit(f"no snapshot in {config.RAW_DIR}; run `ulpe fetch-snapshot` first")
    client = _rpc()
    meta = json.loads(meta_path.read_text())
    last_block = int(_raw_logs()["block_number"].max())  # type: ignore[arg-type]
    blocks, full = snapshot.pick_sample_blocks(
        meta["block"] + 1, last_block, n=config.N_SAMPLES, n_full=config.N_FULL_BOOK
    )
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
    samples = pl.DataFrame(
        states,
        schema={
            "block": pl.Int64,
            "sqrt_price_x96": pl.Int128,
            "tick": pl.Int64,
            "fee_protocol": pl.Int64,
            "liquidity": pl.Int128,
            "full_book": pl.Boolean,
        },
    )
    # onchain_samples.parquet is the skip marker, so it must appear last and atomically.
    write_exact(pl.concat(tick_frames), config.RAW_DIR / "onchain_sample_ticks.parquet")
    write_exact(samples, out)
    print(f"wrote {len(blocks)} samples ({len(full)} full-book)")


def fetch_cex() -> None:
    windows = bigquery.month_windows(config.WINDOW_START, config.WINDOW_END)
    months = [(d.year, d.month) for d, _ in windows]
    binance.fetch_cex(months, config.RAW_DIR)


def labelled_swaps() -> pl.DataFrame:
    path = config.INTERIM_DIR / "swaps.parquet"
    if not path.exists():
        raise SystemExit(f"{path} missing; run `ulpe build` first")
    return flows.label_swaps(read_exact(path), flows.load_labels(config.LABELS_CSV))


def fetch_blocks(dry_run: bool) -> None:
    bots = flows.top_bots(labelled_swaps())
    print(f"top bots: {len(bots)}")
    if dry_run or not (config.RAW_DIR / bq_blocks.BLOCKS_FILE).exists():
        bq_blocks.fetch_blocks(config.RAW_DIR, config.WINDOW_START, config.WINDOW_END, dry_run)
    else:
        print("blocks already downloaded, skipping")
    if dry_run or not bq_blocks.bot_tx_logs_current(config.RAW_DIR, bots):
        bq_blocks.fetch_bot_tx_logs(
            config.RAW_DIR, config.WINDOW_START, config.WINDOW_END, bots, dry_run
        )
    else:
        print("top-bot transaction logs already downloaded for these bots, skipping")


def fetch_transfers() -> None:
    labelled = labelled_swaps()
    bots = flows.top_bots(labelled)
    lo = int(labelled["block_number"].min())  # type: ignore[arg-type]
    hi = int(labelled["block_number"].max())  # type: ignore[arg-type]
    print(f"internal transfers from {len(bots)} top bots, blocks {lo}-{hi}:")
    transfers.fetch_bot_transfers(_rpc(), config.RAW_DIR, bots, lo, hi)


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
    sub.add_parser("fetch-cex", help="download Binance ETHUSDC trades and ETHUSDT 1s klines")
    blocks_cmd = sub.add_parser(
        "fetch-blocks", help="download block miners/base fees and top-bot tx logs (BigQuery)"
    )
    blocks_cmd.add_argument("--dry-run", action="store_true", help="only report bytes scanned")
    sub.add_parser("fetch-transfers", help="download top-bot internal ETH transfers (Alchemy)")
    sub.add_parser("build", help="decode raw data into interim tables")
    sub.add_parser("validate", help="run checks C1-C6 and write data_validation/validation_report")
    sub.add_parser("analyze", help="run checks A1-A6 and write results/ (tables, charts, summary)")
    sub.add_parser("all", help="fetch anything missing, build, then validate")

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
    elif args.command == "fetch-cex":
        fetch_cex()
    elif args.command == "fetch-blocks":
        fetch_blocks(args.dry_run)
    elif args.command == "fetch-transfers":
        fetch_transfers()
    elif args.command == "build":
        try:
            build.build_all(config.RAW_DIR, config.INTERIM_DIR)
        except FileNotFoundError as e:
            raise SystemExit(str(e)) from e
    elif args.command == "validate":
        try:
            status = validate.run_validation()
        except FileNotFoundError as e:
            raise SystemExit(str(e)) from e
        raise SystemExit(0 if status == "PASS" else 1)
    elif args.command == "analyze":
        try:
            status = analysis.run_analysis()
        except (FileNotFoundError, RuntimeError, ValueError) as e:
            raise SystemExit(str(e)) from e
        raise SystemExit(0 if status == "PASS" else 1)
    elif args.command == "all":
        for start, end in bigquery.month_windows(config.WINDOW_START, config.WINDOW_END):
            if not bigquery.raw_logs_path(start, end).exists():
                bigquery.fetch_pool_logs(start, end)
        fetch_snapshot()
        fetch_cex()
        fetch_samples()
        build.build_all(config.RAW_DIR, config.INTERIM_DIR)
        raise SystemExit(0 if validate.run_validation() == "PASS" else 1)


if __name__ == "__main__":
    main()
