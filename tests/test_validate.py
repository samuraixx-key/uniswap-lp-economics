import json
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.validate import (
    CheckResult,
    c2_tick_ok,
    check_c3,
    check_c4,
    check_c6,
    input_hashes,
    replay,
    require_validated,
    write_report,
)


def ev(block: int, idx: int, event: str, **kw: int) -> dict[str, object]:
    row: dict[str, object] = {
        "block_number": block,
        "log_index": idx,
        "event": event,
        "tick": None,
        "sqrt_price_x96": None,
        "liquidity": None,
        "tick_lower": None,
        "tick_upper": None,
        "amount": None,
        "fee_protocol0_new": None,
        "fee_protocol1_new": None,
    }
    row.update(kw)
    return row


SCHEMA = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "event": pl.String,
    "tick": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "liquidity": pl.Int128,
    "tick_lower": pl.Int64,
    "tick_upper": pl.Int64,
    "amount": pl.Int128,
    "fee_protocol0_new": pl.Int64,
    "fee_protocol1_new": pl.Int64,
}


def events(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA)


def fresh_book() -> TickBook:
    b = TickBook(tick=50, sqrt_price_x96=sqrt_at(50), liquidity=0)
    b.apply_mint(-100, 100, 1000)
    return b


def test_c2_rule() -> None:
    assert c2_tick_ok(sqrt_at(10) + 5, 10) == (True, False)
    assert c2_tick_ok(sqrt_at(10), 9) == (True, True)  # downward swap stopping on the boundary
    assert c2_tick_ok(sqrt_at(10) + 5, 9) == (False, False)


def test_replay_consistent_events_pass_and_capture_states() -> None:
    e = events(
        [
            ev(1, 0, "mint", tick_lower=0, tick_upper=200, amount=500),
            # crosses 100 (-1000)
            ev(1, 1, "swap", tick=150, sqrt_price_x96=sqrt_at(150) + 1, liquidity=500),
            ev(2, 0, "set_fee_protocol", fee_protocol0_new=4, fee_protocol1_new=4),
            ev(3, 0, "burn", tick_lower=0, tick_upper=200, amount=500),
        ]
    )
    r = replay(e, fresh_book(), fee_protocol=0, sample_ticks={1: [0, 100], 2: [0]}, full_blocks={2})
    assert r.c1.passed and r.c2.passed
    assert r.states[1]["liquidity"] == 500 and r.states[1]["tick"] == 150
    assert r.states[1]["ticks"] == {0: (500, 500), 100: (1000, -1000)}
    assert r.states[2]["fee_protocol"] == 4 | 4 << 4
    assert set(r.states[2]["ticks"]) == {-100, 0, 100, 200}  # full book


def test_replay_reports_c1_mismatch_with_location() -> None:
    e = events([ev(7, 3, "swap", tick=60, sqrt_price_x96=sqrt_at(60) + 1, liquidity=999)])
    r = replay(e, fresh_book(), fee_protocol=0, sample_ticks={}, full_blocks=set())
    assert not r.c1.passed
    assert r.c1.mismatches[0] == {"block": 7, "log_index": 3, "expected": 999, "replayed": 1000}


def test_c3_compares_exactly() -> None:
    states = {
        5: {
            "sqrt_price_x96": 1,
            "tick": 2,
            "liquidity": 3,
            "fee_protocol": 0,
            "ticks": {10: (4, -4)},
        }
    }
    samples = pl.DataFrame(
        {
            "block": [5],
            "sqrt_price_x96": [1],
            "tick": [2],
            "fee_protocol": [0],
            "liquidity": [3],
            "full_book": [False],
        }
    )
    ticks = pl.DataFrame(
        {"block": [5], "tick": [10], "liquidity_gross": [4], "liquidity_net": [-4]}
    )
    assert check_c3(states, samples, ticks, n_samples=1, n_full=0).passed
    bad = ticks.with_columns(liquidity_net=pl.lit(-5))
    assert not check_c3(states, samples, bad, n_samples=1, n_full=0).passed


def test_c4_snapshot_consistency() -> None:
    ticks = pl.DataFrame(
        {"tick": [-100, 100], "liquidity_gross": [10, 10], "liquidity_net": [10, -10]}
    )
    assert check_c4(ticks, {"tick": 0, "liquidity": 10}).passed
    assert not check_c4(ticks, {"tick": 0, "liquidity": 11}).passed


def test_c6_median_deviation() -> None:
    ts = pl.datetime(2026, 7, 1, time_zone="UTC")
    swaps = pl.DataFrame(
        {"block_timestamp": [1_000_000, 2_000_000], "price_usd": [2000.0, 2001.0]}
    ).with_columns(block_timestamp=ts + pl.duration(microseconds=pl.col("block_timestamp")))
    base = int(swaps["block_timestamp"].dt.epoch("us").min())  # type: ignore[arg-type]
    trades = pl.DataFrame({"ts_us": [base - 10, base + 999_000], "price": [2000.2, 2001.0]})
    r = check_c6(swaps, trades)
    assert r.passed and r.summary["median_bp"] == pytest.approx(0.5, abs=0.01)


def test_report_and_require_validated(tmp_path: Path) -> None:
    ok = CheckResult("C1", True, {"n": 1}, [])
    assert write_report([ok], tmp_path, {"commit": "abc"}) == "PASS"
    require_validated(tmp_path)
    assert "C1" in (tmp_path / "validation_report.md").read_text()
    write_report([ok, CheckResult("C2", False, {}, [{"x": 1}])], tmp_path, {})
    with pytest.raises(RuntimeError, match="FAIL"):
        require_validated(tmp_path)
    assert json.loads((tmp_path / "validation_report.json").read_text())["status"] == "FAIL"


def test_require_validated_missing_report(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="ulpe validate"):
        require_validated(tmp_path)


def _c6_inputs(trade_offset_us: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    ts = pl.datetime(2026, 7, 1, time_zone="UTC")
    swaps = pl.DataFrame({"block_timestamp": [1_000_000, 2_000_000], "price_usd": [2000.0, 2001.0]})
    swaps = swaps.with_columns(
        block_timestamp=ts + pl.duration(microseconds=pl.col("block_timestamp"))
    )
    base = int(swaps["block_timestamp"].dt.epoch("us").min())  # type: ignore[arg-type]
    trades = pl.DataFrame({"ts_us": [base + trade_offset_us], "price": [2000.0]})
    return swaps, trades


def test_c6_fails_when_a_swap_has_no_prior_trade() -> None:
    swaps, trades = _c6_inputs(500_000)  # first swap precedes the only trade
    r = check_c6(swaps, trades)
    assert not r.passed
    assert r.summary["unmatched"] == 1


def test_c6_fails_when_no_swap_is_matched() -> None:
    swaps, trades = _c6_inputs(10_000_000)
    r = check_c6(swaps, trades)
    assert not r.passed
    assert r.summary["unmatched"] == 2 and r.summary["matched"] == 0


def test_c6_fails_with_no_swaps() -> None:
    swaps, trades = _c6_inputs(-10)
    assert not check_c6(swaps.head(0), trades).passed


def test_c1_c2_fail_without_swaps() -> None:
    e = events([ev(1, 0, "mint", tick_lower=0, tick_upper=200, amount=500)])
    r = replay(e, fresh_book(), fee_protocol=0, sample_ticks={}, full_blocks=set())
    assert not r.c1.passed and not r.c2.passed
    assert r.c1.summary["swaps"] == 0


def _c3_inputs() -> tuple[dict[int, dict[str, object]], pl.DataFrame, pl.DataFrame]:
    states: dict[int, dict[str, object]] = {
        5: {
            "sqrt_price_x96": 1,
            "tick": 2,
            "liquidity": 3,
            "fee_protocol": 0,
            "ticks": {10: (4, -4)},
        }
    }
    samples = pl.DataFrame(
        {
            "block": [5],
            "sqrt_price_x96": [1],
            "tick": [2],
            "fee_protocol": [0],
            "liquidity": [3],
            "full_book": [True],
        }
    )
    ticks = pl.DataFrame(
        {"block": [5], "tick": [10], "liquidity_gross": [4], "liquidity_net": [-4]}
    )
    return states, samples, ticks


def test_c3_requires_expected_sample_counts() -> None:
    states, samples, ticks = _c3_inputs()
    assert check_c3(states, samples, ticks, n_samples=1, n_full=1).passed
    assert not check_c3(states, samples, ticks, n_samples=2, n_full=1).passed  # too few samples
    assert not check_c3(states, samples, ticks, n_samples=1, n_full=2).passed  # too few full books
    assert not check_c3(states, samples, ticks).passed  # defaults demand the configured counts


def test_c3_fails_on_empty_inputs() -> None:
    states, samples, ticks = _c3_inputs()
    assert not check_c3({}, samples.head(0), ticks, n_samples=0, n_full=0).passed
    assert not check_c3(states, samples, ticks.head(0), n_samples=1, n_full=1).passed


def test_c3_fails_when_a_sample_block_has_no_onchain_tick_rows() -> None:
    states, samples, ticks = _c3_inputs()
    other = ticks.with_columns(block=pl.lit(99))  # lookup for block 5 misses
    assert not check_c3(states, samples, other, n_samples=1, n_full=1).passed


def test_report_with_no_results_is_not_pass(tmp_path: Path) -> None:
    assert write_report([], tmp_path, {}) == "FAIL"


def test_input_hashes_cover_every_input(tmp_path: Path) -> None:
    raw, interim = tmp_path / "raw", tmp_path / "interim"
    (raw / "binance").mkdir(parents=True)
    interim.mkdir()
    names = [
        raw / "pool_logs_a.parquet",
        raw / "tickbook_snapshot.parquet",
        raw / "snapshot_meta.json",
        raw / "onchain_samples.parquet",
        raw / "onchain_sample_ticks.parquet",
        raw / "binance" / "x.zip",
        interim / "events.parquet",
        interim / "swaps.parquet",
        interim / "cex_ethusdc.parquet",
    ]
    for p in names:
        p.write_bytes(p.name.encode())
    hashes = input_hashes(raw, interim)
    assert set(hashes) == {p.relative_to(tmp_path).as_posix() for p in names}
    assert all(len(h) == 16 for h in hashes.values())
