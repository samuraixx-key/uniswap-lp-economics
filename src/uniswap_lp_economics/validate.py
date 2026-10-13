"""Validation checks C1-C6 (see the data-foundation spec) and the committed report."""

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from uniswap_lp_economics import config
from uniswap_lp_economics.build import load_snapshot_meta
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick, get_tick_at_sqrt_ratio

MAX_LISTED = 20
C6_MAX_MEDIAN_BP = 10.0


@dataclass
class CheckResult:
    name: str
    passed: bool
    summary: dict[str, Any]
    mismatches: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReplayResult:
    c1: CheckResult
    c2: CheckResult
    states: dict[int, dict[str, Any]]


def c2_tick_ok(sqrt_price_x96: int, tick: int) -> tuple[bool, bool]:
    t = get_tick_at_sqrt_ratio(sqrt_price_x96)
    if tick == t:
        return True, False
    boundary = tick == t - 1 and sqrt_price_x96 == get_sqrt_ratio_at_tick(t)
    return boundary, boundary


def _capture(book: TickBook, fee_protocol: int, ticks: list[int] | None) -> dict[str, Any]:
    wanted = book.initialized_ticks() if ticks is None else ticks
    return {
        "sqrt_price_x96": book.sqrt_price_x96,
        "tick": book.tick,
        "liquidity": book.liquidity,
        "fee_protocol": fee_protocol,
        "ticks": {
            t: (book.liquidity_gross.get(t, 0), book.liquidity_net.get(t, 0)) for t in wanted
        },
    }


def replay(
    events: pl.DataFrame,
    book: TickBook,
    fee_protocol: int,
    sample_ticks: dict[int, list[int]],
    full_blocks: set[int],
) -> ReplayResult:
    """Replay events in (block, log_index) order; check C1/C2, capture state after sample blocks."""
    pending = sorted(set(sample_ticks) | full_blocks)
    states: dict[int, dict[str, Any]] = {}
    c1_bad: list[dict[str, Any]] = []
    c2_bad: list[dict[str, Any]] = []
    n_swaps = c1_count = c2_count = boundary = 0
    cols = [
        "block_number",
        "log_index",
        "event",
        "tick",
        "sqrt_price_x96",
        "liquidity",
        "tick_lower",
        "tick_upper",
        "amount",
        "fee_protocol0_new",
        "fee_protocol1_new",
    ]

    def flush(before_block: int | None) -> None:
        while pending and (before_block is None or pending[0] < before_block):
            b = pending.pop(0)
            states[b] = _capture(
                book, fee_protocol, None if b in full_blocks else sample_ticks.get(b, [])
            )

    for blk, idx, kind, tick, sqrt, liq, lo, hi, amount, fp0, fp1 in (
        events.sort("block_number", "log_index").select(cols).iter_rows()
    ):
        flush(blk)
        if kind == "mint":
            book.apply_mint(lo, hi, amount)
        elif kind == "burn":
            book.apply_burn(lo, hi, amount)
        elif kind == "set_fee_protocol":
            fee_protocol = fp0 + (fp1 << 4)
        elif kind == "swap":
            n_swaps += 1
            book.apply_swap(sqrt, tick)
            if book.liquidity != liq:
                c1_count += 1
                if len(c1_bad) < MAX_LISTED:
                    c1_bad.append(
                        {
                            "block": blk,
                            "log_index": idx,
                            "expected": liq,
                            "replayed": book.liquidity,
                        }
                    )
                book.liquidity = liq  # resync so one bug doesn't cascade into every later swap
            ok, is_boundary = c2_tick_ok(sqrt, tick)
            boundary += is_boundary
            if not ok:
                c2_count += 1
                if len(c2_bad) < MAX_LISTED:
                    c2_bad.append(
                        {"block": blk, "log_index": idx, "tick": tick, "sqrt_price_x96": sqrt}
                    )
    flush(None)

    c1 = CheckResult(
        "C1 active liquidity per swap",
        c1_count == 0,
        {"swaps": n_swaps, "mismatches": c1_count},
        c1_bad,
    )
    c2 = CheckResult(
        "C2 tick vs sqrt price",
        c2_count == 0,
        {"swaps": n_swaps, "mismatches": c2_count, "boundary_cases": boundary},
        c2_bad,
    )
    return ReplayResult(c1, c2, states)


def check_c3(
    states: dict[int, dict[str, Any]], samples: pl.DataFrame, sample_ticks: pl.DataFrame
) -> CheckResult:
    bad: list[dict[str, Any]] = []
    n_bad = n_ticks = 0
    ticks_by_block = sample_ticks.partition_by("block", as_dict=True)
    for row in samples.iter_rows(named=True):
        b = row["block"]
        s = states[b]
        for key in ("sqrt_price_x96", "tick", "liquidity", "fee_protocol"):
            if s[key] != row[key]:
                n_bad += 1
                if len(bad) < MAX_LISTED:
                    bad.append({"block": b, "field": key, "onchain": row[key], "replayed": s[key]})
        onchain = ticks_by_block.get((b,), pl.DataFrame())
        onchain_ticks = (
            {
                t: (g, n)
                for t, g, n in onchain.select(
                    "tick", "liquidity_gross", "liquidity_net"
                ).iter_rows()
            }
            if onchain.height
            else {}
        )
        replayed = s["ticks"]
        compare = set(onchain_ticks) | (set(replayed) if row["full_book"] else set())
        for t in compare:
            n_ticks += 1
            if onchain_ticks.get(t, (0, 0)) != replayed.get(t, (0, 0)):
                n_bad += 1
                if len(bad) < MAX_LISTED:
                    bad.append(
                        {
                            "block": b,
                            "tick": t,
                            "onchain": onchain_ticks.get(t),
                            "replayed": replayed.get(t),
                        }
                    )
    return CheckResult(
        "C3 on-chain samples",
        n_bad == 0,
        {
            "blocks": samples.height,
            "full_book_blocks": int(samples["full_book"].sum()),
            "ticks_compared": n_ticks,
            "mismatches": n_bad,
        },
        bad,
    )


def check_c4(ticks: pl.DataFrame, meta: dict[str, int]) -> CheckResult:
    net = dict(zip(ticks["tick"].to_list(), ticks["liquidity_net"].to_list(), strict=True))
    total = sum(net.values())
    rebuilt = sum(v for t, v in net.items() if t <= meta["tick"])
    ok = total == 0 and rebuilt == meta["liquidity"]
    return CheckResult(
        "C4 snapshot self-consistency",
        ok,
        {
            "initialized_ticks": len(net),
            "sum_liquidity_net": total,
            "rebuilt_active": rebuilt,
            "onchain_liquidity": meta["liquidity"],
        },
    )


def check_c5(
    raw_logs: pl.DataFrame, events: pl.DataFrame, trades: pl.DataFrame, binance_dir: Path
) -> CheckResult:
    start = datetime.combine(config.WINDOW_START, datetime.min.time(), UTC)
    end = datetime.combine(config.WINDOW_END, datetime.min.time(), UTC)
    dupes = raw_logs.height - raw_logs.select("block_number", "log_index").n_unique()
    unjoined = raw_logs["from_address"].null_count()
    ts = raw_logs["block_timestamp"]
    outside = raw_logs.filter((ts < start) | (ts >= end)).height
    other = events.filter(pl.col("event") == "other").height
    bad_sums = []
    zips = sorted(binance_dir.glob("*.zip"))
    for z in zips:
        checksum = z.with_name(z.name + ".CHECKSUM")
        if (
            not checksum.exists()
            or hashlib.sha256(z.read_bytes()).hexdigest() != checksum.read_text().split()[0]
        ):
            bad_sums.append(z.name)  # a missing checksum file counts as unverified
    max_gap_s = float(trades["ts_us"].diff().max() or 0) / 1e6  # type: ignore[arg-type]
    ok = dupes == 0 and unjoined == 0 and outside == 0 and not bad_sums and len(zips) > 0
    return CheckResult(
        "C5 raw data integrity",
        ok,
        {
            "logs": raw_logs.height,
            "duplicates": dupes,
            "unjoined_tx": unjoined,
            "outside_window": outside,
            "other_events": other,
            "binance_files": len(zips),
            "bad_checksums": bad_sums,
            "max_binance_trade_gap_s": max_gap_s,
        },
    )


def check_c6(swaps: pl.DataFrame, trades: pl.DataFrame) -> CheckResult:
    s = swaps.select(ts_us=pl.col("block_timestamp").dt.epoch("us"), price_usd="price_usd").sort(
        "ts_us"
    )
    joined = s.join_asof(
        trades.select("ts_us", "price").sort("ts_us"), on="ts_us", strategy="backward"
    )
    dev = (joined["price_usd"] / joined["price"] - 1).abs() * 1e4
    median = float(dev.median() or 0.0)  # type: ignore[arg-type]
    return CheckResult(
        "C6 pool vs Binance sanity",
        median < C6_MAX_MEDIAN_BP,
        {
            "swaps": joined.height,
            "median_bp": median,
            "p95_bp": float(dev.quantile(0.95) or 0.0),
            "bound_bp": C6_MAX_MEDIAN_BP,
        },
    )


def write_report(results: list[CheckResult], out_dir: Path, extra: dict[str, Any]) -> str:
    status = "PASS" if all(r.passed for r in results) else "FAIL"
    out_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "status": status,
        **extra,
        "checks": [
            {"name": r.name, "passed": r.passed, "summary": r.summary, "mismatches": r.mismatches}
            for r in results
        ],
    }
    (out_dir / "validation_report.json").write_text(json.dumps(body, indent=2, default=str))
    lines = [f"# Validation report: **{status}**", ""]
    lines += [f"- {k}: `{v}`" for k, v in extra.items()]
    lines += ["", "| Check | Result | Summary |", "|---|---|---|"]
    lines += [
        f"| {r.name} | {'PASS' if r.passed else 'FAIL'} | "
        + ", ".join(f"{k}={v}" for k, v in r.summary.items())
        + " |"
        for r in results
    ]
    for r in results:
        if r.mismatches:
            lines += [
                "",
                f"## {r.name}: first mismatches",
                "",
                "```",
                *map(str, r.mismatches),
                "```",
            ]
    (out_dir / "validation_report.md").write_text("\n".join(lines) + "\n")
    return status


def require_validated(report_dir: Path = config.VALIDATION_DIR) -> None:
    path = report_dir / "validation_report.json"
    if not path.exists():
        raise RuntimeError(f"{path} missing; run `ulpe validate` first")
    status = json.loads(path.read_text())["status"]
    if status != "PASS":
        raise RuntimeError(f"validation status is {status}; fix the data before analysis")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run_validation() -> str:
    raw, interim = config.RAW_DIR, config.INTERIM_DIR
    for p in (
        interim / "events.parquet",
        interim / "swaps.parquet",
        interim / "cex_ethusdc.parquet",
    ):
        if not p.exists():
            raise FileNotFoundError(f"{p} missing; run `ulpe build` first")
    for p in (raw / "onchain_samples.parquet", raw / "onchain_sample_ticks.parquet"):
        if not p.exists():
            raise FileNotFoundError(f"{p} missing; run `ulpe fetch-samples` first")
    meta = load_snapshot_meta(raw)
    snap = pl.read_parquet(raw / "tickbook_snapshot.parquet")
    events = pl.read_parquet(interim / "events.parquet")
    swaps = pl.read_parquet(interim / "swaps.parquet")
    trades = pl.read_parquet(interim / "cex_ethusdc.parquet")
    samples = pl.read_parquet(raw / "onchain_samples.parquet")
    sample_ticks = pl.read_parquet(raw / "onchain_sample_ticks.parquet")
    raw_logs = pl.read_parquet(sorted(raw.glob("pool_logs_*.parquet")))

    full = set(samples.filter("full_book")["block"].to_list())
    wanted = {
        b: g["tick"].to_list()
        for (b,), g in sample_ticks.partition_by("block", as_dict=True).items()
    }
    for b in samples["block"].to_list():
        wanted.setdefault(b, [])
    r = replay(events, TickBook.from_snapshot(snap, meta), int(meta["fee_protocol"]), wanted, full)
    results = [
        r.c1,
        r.c2,
        check_c3(r.states, samples, sample_ticks),
        check_c4(snap, meta),
        check_c5(raw_logs, events, trades, raw / "binance"),
        check_c6(swaps, trades),
    ]
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    extra = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": commit,
        "window": f"[{config.WINDOW_START}, {config.WINDOW_END})",
        "snapshot_block": meta["block"],
        "snapshot_fee_protocol": meta["fee_protocol"],
        "input_sha256_16": {p.name: _file_hash(p) for p in sorted(raw.glob("pool_logs_*.parquet"))},
    }
    status = write_report(results, config.VALIDATION_DIR, extra)
    for res in results:
        print(f"{'PASS' if res.passed else 'FAIL'}  {res.name}: {res.summary}")
    return status
