"""Command-line entry point: `uv run ulpe <command>`."""

import argparse
from datetime import date

from uniswap_lp_economics.data import bigquery


def main() -> None:
    parser = argparse.ArgumentParser(prog="ulpe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch-logs", help="download pool logs from BigQuery, one file per month"
    )
    fetch.add_argument("--start", type=date.fromisoformat, required=True)
    fetch.add_argument("--end", type=date.fromisoformat, required=True, help="exclusive")
    fetch.add_argument("--dry-run", action="store_true", help="only report bytes scanned")

    args = parser.parse_args()
    if args.command == "fetch-logs":
        for start, end in bigquery.month_windows(args.start, args.end):
            if not args.dry_run and bigquery.raw_logs_path(start, end).exists():
                print(f"{start} -> {end}: already downloaded, skipping")
                continue
            bigquery.fetch_pool_logs(start, end, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
