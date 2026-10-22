"""Command-line entry point: `uv run ulpe <command>`."""

import argparse
import json
from datetime import UTC, date, datetime
from typing import NoReturn

import polars as pl

from uniswap_lp_economics import analyze as analysis
from uniswap_lp_economics import build, config, flows, snapshot, validate
from uniswap_lp_economics.data import (
    bigquery,
    binance,
    block_timing,
    builders,
    chain_state,
    history,
    relays,
    transfers,
)
from uniswap_lp_economics.data import blocks as bq_blocks
from uniswap_lp_economics.io import read_exact, write_exact, write_text_atomic
from uniswap_lp_economics.lp import analyze as lp_analysis_module
from uniswap_lp_economics.lp import payouts
from uniswap_lp_economics.lp.positions import build_positions
from uniswap_lp_economics.rpc import RpcClient
from uniswap_lp_economics.viz import render as viz_render


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


def refuse_paid_query(what: str, command: str, rerun: str = "all") -> NoReturn:
    """Stop before a billable BigQuery query that --confirm-cost did not allow. `rerun`: the
    command to repeat with the flag (`ulpe all`, or the standalone fetch)."""
    raise SystemExit(
        f"{what} missing: `ulpe {command}` runs a billable BigQuery query. Check its size with "
        f"`ulpe {command} --dry-run`, then run `ulpe {rerun} --confirm-cost`"
    )


def fetch_blocks(dry_run: bool, confirm_cost: bool, rerun: str = "all") -> None:
    """Without confirm_cost (and without dry_run), stop instead of querying BigQuery."""
    have_blocks = (config.RAW_DIR / bq_blocks.BLOCKS_FILE).exists()
    if not (dry_run or have_blocks or confirm_cost):
        refuse_paid_query("block fee recipients and base fees", "fetch-blocks", rerun)
    bots = flows.top_bots(labelled_swaps())
    print(f"top bots: {len(bots)}")
    if dry_run or not have_blocks:
        bq_blocks.fetch_blocks(config.RAW_DIR, config.WINDOW_START, config.WINDOW_END, dry_run)
    else:
        print("blocks already downloaded, skipping")
    if dry_run or not bq_blocks.bot_tx_logs_current(config.RAW_DIR, bots):
        if not (dry_run or confirm_cost):
            refuse_paid_query("logs in top-bot transactions", "fetch-blocks", rerun)
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


def fetch_chain_state() -> None:
    """D2-D4 (spec 3.1). Fee state, then position state and owner code once the history exists."""
    client = _rpc()
    meta = build.load_snapshot_meta(config.RAW_DIR)
    folder = config.RAW_DIR / chain_state.CHAIN_DIR
    if (folder / chain_state.SNAPSHOT_FEES).exists():
        print("snapshot fee state already downloaded, skipping")
    else:
        ticks = read_exact(config.RAW_DIR / "tickbook_snapshot.parquet")["tick"].to_list()
        chain_state.fetch_snapshot_fees(client, config.RAW_DIR, int(meta["block"]), ticks)
    if (folder / chain_state.SAMPLE_FEES).exists():
        print("sample fee state already downloaded, skipping")
    else:
        sample_ticks = read_exact(config.RAW_DIR / "onchain_sample_ticks.parquet")
        chain_state.fetch_sample_fees(client, config.RAW_DIR, sample_ticks.select("block", "tick"))
    hist = config.RAW_DIR / history.HISTORY_DIR / history.POOL_FILE
    if not hist.exists():
        print("no history yet: position state comes after `ulpe fetch-history`")
        return
    done = (chain_state.START_POSITIONS, chain_state.END_POSITIONS, chain_state.OWNER_CODE)
    if all((folder / name).exists() for name in done):
        print("position state and owner code already downloaded, skipping")
        return
    data = build_positions(*history.load_history(config.RAW_DIR))
    snap = int(meta["block"])
    end_block = int(
        pl.read_parquet(config.RAW_DIR / bq_blocks.BLOCKS_FILE)["block_number"].max()  # type: ignore[arg-type]
    )
    for name, block, include_new in (
        (chain_state.START_POSITIONS, snap, False),
        (chain_state.END_POSITIONS, end_block, True),
    ):
        if (folder / name).exists():
            print(f"{name} already downloaded, skipping")
            continue
        keys, tokens = chain_state.state_targets(data, block, snap, include_new)
        chain_state.fetch_position_state(client, config.RAW_DIR, block, keys, tokens, name)
    active = data.positions.filter(
        pl.col("position_id").is_in(chain_state.window_active_ids(data, snap))
    )
    addresses = sorted(set(active["lp"].to_list()) | set(active["owner"].to_list()))
    chain_state.fetch_owner_code(client, config.RAW_DIR, addresses, end_block)


def fetch_price_history() -> None:
    """D7: Binance ETHUSDT 1-minute klines from the pool's creation to the window start."""
    months = [
        (d.year, d.month)
        for d, _ in bigquery.month_windows(
            date(config.POOL_CREATED.year, config.POOL_CREATED.month, 1), config.WINDOW_START
        )
    ]
    binance.fetch_price_history(months, config.RAW_DIR)


def fetch_relays() -> None:
    """D6: relay-reported proposer payments for a random sample of window blocks."""
    blocks = pl.read_parquet(config.RAW_DIR / bq_blocks.BLOCKS_FILE)["block_number"]
    relays.fetch_relay_sample(config.RAW_DIR, int(blocks.min()), int(blocks.max()))  # type: ignore[arg-type]
    relays.retry_unchecked(config.RAW_DIR)
    if (config.RAW_DIR / builders.BUILDERS_DIR / builders.LAST_TX).exists():
        relays.fetch_holdout(config.RAW_DIR, _block_classes())
    else:
        print("holdout waits for `ulpe fetch-builders` (last-transaction table missing)")


def _block_classes() -> pl.DataFrame:
    block_revenue, _, _ = builders.load_builders(config.RAW_DIR)
    return payouts.block_classes(block_revenue, builders.load_last_tx(config.RAW_DIR))


def fetch_payout_code() -> None:
    """Code of each payout recipient at its first and last payout block (RPC)."""
    reads = payouts.recipient_reads(_block_classes())
    builders.fetch_payout_code(_rpc(), config.RAW_DIR, reads)
    print(f"payout recipient code: {len(reads)} reads")


def fetch_timing() -> None:
    """Sub-project 4: winning-bid times for the relay sample's blocks (free relay calls)."""
    blocks = pl.read_parquet(config.RAW_DIR / bq_blocks.BLOCKS_FILE)["block_number"]
    block_timing.fetch_block_timing(config.RAW_DIR, int(blocks.min()), int(blocks.max()))  # type: ignore[arg-type]


def fetch_logs(confirm_cost: bool) -> None:
    """Pool logs for every window month not yet on disk (`ulpe all`)."""
    missing = [
        (start, end)
        for start, end in bigquery.month_windows(config.WINDOW_START, config.WINDOW_END)
        if not bigquery.raw_logs_path(start, end).exists()
    ]
    if missing and not confirm_cost:
        refuse_paid_query(
            "pool logs", f"fetch-logs --start {config.WINDOW_START} --end {config.WINDOW_END}"
        )
    for start, end in missing:
        bigquery.fetch_pool_logs(start, end)


def fetch_builders(confirm_cost: bool) -> None:
    """D5 (`ulpe all`): the four aggregated builder tables, unless all of them are on disk."""
    folder = config.RAW_DIR / builders.BUILDERS_DIR
    names = (
        builders.BLOCK_REVENUE,
        builders.TX_DIRECT,
        builders.TX_OTHER_LOGS,
        builders.LAST_TX,
    )
    if all((folder / name).exists() for name in names):
        print("builder tables already downloaded, skipping")
        return
    if not confirm_cost:
        refuse_paid_query("builder revenue and payment tables", "fetch-builders")
    builders.fetch_builders(
        config.RAW_DIR, config.WINDOW_START, config.WINDOW_END, confirm_cost=confirm_cost
    )


# The whole pipeline, in order. fetch-chain-state appears twice: its fee-state part runs before
# the history exists, its position part needs the history.
ALL_STEPS = (
    "fetch-logs",
    "fetch-snapshot",
    "fetch-cex",
    "fetch-samples",
    "build",
    "validate",
    "fetch-blocks",
    "fetch-transfers",
    "analyze",
    "fetch-chain-state",
    "fetch-history",
    "fetch-chain-state",
    "fetch-price-history",
    "fetch-builders",
    "fetch-payout-code",
    "fetch-relays",
    "fetch-timing",
    "lp",
    "figures",
)


def run_step(name: str, confirm_cost: bool) -> str:
    """Run one pipeline step; "PASS"/"FAIL" for the gated ones (validate, analyze, lp), else "OK".

    Without confirm_cost no billable BigQuery query runs: a BigQuery step whose output is missing
    stops the run with a message (fetch-history with its own refusal, after a free dry run)."""
    if name == "fetch-logs":
        fetch_logs(confirm_cost)
    elif name == "fetch-snapshot":
        fetch_snapshot()
    elif name == "fetch-cex":
        fetch_cex()
    elif name == "fetch-samples":
        fetch_samples()
    elif name == "build":
        build.build_all(config.RAW_DIR, config.INTERIM_DIR)
    elif name == "validate":
        return validate.run_validation()
    elif name == "fetch-blocks":
        fetch_blocks(dry_run=False, confirm_cost=confirm_cost)
    elif name == "fetch-transfers":
        fetch_transfers()
    elif name == "analyze":
        return analysis.run_analysis()
    elif name == "fetch-chain-state":
        fetch_chain_state()
    elif name == "fetch-history":
        history.fetch_history(config.RAW_DIR, config.POOL_CREATED, config.WINDOW_END, confirm_cost)
    elif name == "fetch-price-history":
        fetch_price_history()
    elif name == "fetch-builders":
        fetch_builders(confirm_cost)
    elif name == "fetch-payout-code":
        fetch_payout_code()
    elif name == "fetch-relays":
        fetch_relays()
    elif name == "fetch-timing":
        fetch_timing()
    elif name == "lp":
        return lp_analysis_module.run_lp()
    elif name == "figures":
        try:
            return viz_render.run_figures()
        except FileNotFoundError as e:
            raise SystemExit(str(e)) from None
    else:
        raise ValueError(f"unknown pipeline step {name!r}")
    return "OK"


def main() -> None:
    parser = argparse.ArgumentParser(prog="ulpe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch-logs", help="download pool logs from BigQuery, one file per month"
    )
    fetch.add_argument("--start", type=date.fromisoformat, required=True)
    fetch.add_argument("--end", type=date.fromisoformat, required=True, help="exclusive")
    fetch.add_argument("--dry-run", action="store_true", help="only report bytes scanned")
    fetch.add_argument("--confirm-cost", action="store_true", help="allow the paid queries")
    sub.add_parser("fetch-snapshot", help="read the full tick book just before the window (RPC)")
    sub.add_parser("fetch-samples", help="read on-chain state at 500 random blocks (RPC)")
    sub.add_parser("fetch-cex", help="download Binance ETHUSDC trades and ETHUSDT 1s klines")
    sub.add_parser(
        "fetch-price-history",
        help="Binance ETHUSDT 1-minute klines since 2021 (for lifetime P&L)",
    )
    blocks_cmd = sub.add_parser(
        "fetch-blocks", help="download block miners/base fees and top-bot tx logs (BigQuery)"
    )
    blocks_cmd.add_argument("--dry-run", action="store_true", help="only report bytes scanned")
    blocks_cmd.add_argument("--confirm-cost", action="store_true", help="allow the paid queries")
    sub.add_parser("fetch-transfers", help="download top-bot internal ETH transfers (Alchemy)")
    sub.add_parser("fetch-chain-state", help="read pool fee and position state (RPC)")
    hist = sub.add_parser(
        "fetch-history",
        help="pool and position-manager history since 2021 (one paid BigQuery query)",
    )
    hist.add_argument("--dry-run", action="store_true", help="only report bytes scanned")
    hist.add_argument("--confirm-cost", action="store_true", help="allow the paid stage-1 query")
    builders_cmd = sub.add_parser(
        "fetch-builders",
        help="aggregated builder revenue and payment tables (paid BigQuery; needs --confirm-cost)",
    )
    builders_cmd.add_argument("--dry-run", action="store_true", help="only report bytes scanned")
    builders_cmd.add_argument(
        "--confirm-cost", action="store_true", help="allow the paid BigQuery queries"
    )
    sub.add_parser(
        "fetch-payout-code", help="code of the payout recipients at their first/last block (RPC)"
    )
    sub.add_parser("fetch-relays", help="relay-reported proposer payments for a block sample")
    sub.add_parser("fetch-timing", help="winning-bid times for the relay sample's blocks")
    sub.add_parser("build", help="decode raw data into interim tables")
    sub.add_parser("validate", help="run checks C1-C6 and write data_validation/validation_report")
    sub.add_parser("analyze", help="run checks A1-A6 and write results/ (tables, summary)")
    sub.add_parser("lp", help="LP P&L and LVR: checks L1-L7, results/ (sub-project 3)")
    sub.add_parser("figures", help="render results/figures from results/ (light SVG)")
    all_cmd = sub.add_parser(
        "all", help="run the whole pipeline (the paid BigQuery queries need --confirm-cost)"
    )
    all_cmd.add_argument(
        "--confirm-cost",
        action="store_true",
        help="allow the paid BigQuery queries (history and builders; logs and blocks if missing)",
    )

    args = parser.parse_args()
    if args.command == "fetch-logs":
        windows = bigquery.month_windows(args.start, args.end)
        missing = [w for w in windows if not bigquery.raw_logs_path(*w).exists()]
        if missing and not (args.dry_run or args.confirm_cost):
            command = f"fetch-logs --start {args.start} --end {args.end}"
            refuse_paid_query("pool logs", command, rerun=command)
        for start, end in windows:
            if not args.dry_run and (start, end) not in missing:
                print(f"{start} -> {end}: already downloaded, skipping")
                continue
            bigquery.fetch_pool_logs(start, end, dry_run=args.dry_run)
    elif args.command == "fetch-snapshot":
        fetch_snapshot()
    elif args.command == "fetch-samples":
        fetch_samples()
    elif args.command == "fetch-cex":
        fetch_cex()
    elif args.command == "fetch-price-history":
        fetch_price_history()
    elif args.command == "fetch-blocks":
        fetch_blocks(args.dry_run, args.confirm_cost, rerun="fetch-blocks")
    elif args.command == "fetch-transfers":
        fetch_transfers()
    elif args.command == "fetch-chain-state":
        fetch_chain_state()
    elif args.command == "fetch-history":
        history.fetch_history(
            config.RAW_DIR, config.POOL_CREATED, config.WINDOW_END, args.confirm_cost, args.dry_run
        )
    elif args.command == "fetch-builders":
        builders.fetch_builders(
            config.RAW_DIR, config.WINDOW_START, config.WINDOW_END, args.dry_run, args.confirm_cost
        )
    elif args.command == "fetch-payout-code":
        fetch_payout_code()
    elif args.command == "fetch-relays":
        fetch_relays()
    elif args.command == "fetch-timing":
        fetch_timing()
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
    elif args.command == "lp":
        try:
            status = lp_analysis_module.run_lp()
        except (FileNotFoundError, RuntimeError, ValueError) as e:
            raise SystemExit(str(e)) from e
        raise SystemExit(0 if status == "PASS" else 1)
    elif args.command == "figures":
        run_step("figures", False)
    elif args.command == "all":
        try:
            for step in ALL_STEPS:
                if run_step(step, args.confirm_cost) == "FAIL":
                    raise SystemExit(1)
        except (FileNotFoundError, RuntimeError, ValueError) as e:
            raise SystemExit(str(e)) from e
        raise SystemExit(0)


if __name__ == "__main__":
    main()
