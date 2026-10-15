import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics import cli, config
from uniswap_lp_economics.data import bigquery, builders, history
from uniswap_lp_economics.data import blocks as bq_blocks


def test_all_runs_every_step_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(cli, "run_step", lambda name, confirm_cost: ran.append(name) or "PASS")
    monkeypatch.setattr(sys, "argv", ["ulpe", "all", "--confirm-cost"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    assert ran == list(cli.ALL_STEPS)
    assert (
        ran.index("validate") < ran.index("analyze") < ran.index("fetch-history") < ran.index("lp")
    )


def test_all_without_the_flag_stops_at_the_paid_query(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []

    def step(name: str, confirm_cost: bool) -> str:
        ran.append(name)
        if name == "fetch-history" and not confirm_cost:
            raise SystemExit("stage 1 is a paid query; run with --confirm-cost")
        return "PASS"

    monkeypatch.setattr(cli, "run_step", step)
    monkeypatch.setattr(sys, "argv", ["ulpe", "all"])
    with pytest.raises(SystemExit, match="paid query"):
        cli.main()
    assert ran[-1] == "fetch-history"


def test_all_stops_with_exit_1_when_a_gated_step_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []

    def step(name: str, confirm_cost: bool) -> str:
        ran.append(name)
        return "FAIL" if name == "analyze" else "PASS"

    monkeypatch.setattr(cli, "run_step", step)
    monkeypatch.setattr(sys, "argv", ["ulpe", "all", "--confirm-cost"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 1
    assert ran[-1] == "analyze"


def test_all_turns_a_missing_input_into_a_clean_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def step(name: str, confirm_cost: bool) -> str:
        raise FileNotFoundError("data/raw/blocks.parquet missing; run `ulpe fetch-blocks` first")

    monkeypatch.setattr(cli, "run_step", step)
    monkeypatch.setattr(sys, "argv", ["ulpe", "all"])
    with pytest.raises(SystemExit, match="ulpe fetch-blocks"):
        cli.main()


def test_unknown_step_raises() -> None:
    with pytest.raises(ValueError, match="unknown pipeline step"):
        cli.run_step("fetch-everything", True)


def _no_query(*args: Any, **kwargs: Any) -> None:
    raise AssertionError("a BigQuery query was issued")


def test_missing_builders_without_the_flag_stop_before_any_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(builders, "fetch_builders", _no_query)
    with pytest.raises(SystemExit, match="--confirm-cost"):
        cli.run_step("fetch-builders", False)


def test_missing_builders_with_the_flag_are_fetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(
        builders,
        "fetch_builders",
        lambda raw, s, e, confirm_cost=False: calls.append((raw, s, e, confirm_cost)),
    )
    assert cli.run_step("fetch-builders", True) == "OK"
    assert calls == [(tmp_path, config.WINDOW_START, config.WINDOW_END, True)]  # flag passed on


def test_builders_on_disk_are_skipped_without_bigquery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / builders.BUILDERS_DIR
    folder.mkdir()
    for name in (builders.BLOCK_REVENUE, builders.TX_DIRECT, builders.TX_OTHER_LOGS):
        (folder / name).write_bytes(b"")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(builders, "fetch_builders", _no_query)
    assert cli.run_step("fetch-builders", False) == "OK"


def test_history_step_passes_the_flag_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(history, "fetch_history", lambda *a: calls.append(a))
    cli.run_step("fetch-history", False)
    cli.run_step("fetch-history", True)
    assert calls == [
        (tmp_path, config.POOL_CREATED, config.WINDOW_END, False),
        (tmp_path, config.POOL_CREATED, config.WINDOW_END, True),
    ]


def test_missing_pool_logs_without_the_flag_stop_before_any_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(bigquery, "raw_logs_path", lambda s, e: tmp_path / f"{s}_{e}.parquet")
    monkeypatch.setattr(bigquery, "fetch_pool_logs", _no_query)
    with pytest.raises(SystemExit, match="--confirm-cost"):
        cli.run_step("fetch-logs", False)


def test_pool_logs_on_disk_need_no_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bigquery, "raw_logs_path", lambda s, e: tmp_path / f"{s}_{e}.parquet")
    for s, e in bigquery.month_windows(config.WINDOW_START, config.WINDOW_END):
        bigquery.raw_logs_path(s, e).write_bytes(b"")
    monkeypatch.setattr(bigquery, "fetch_pool_logs", _no_query)
    assert cli.run_step("fetch-logs", False) == "OK"


def test_missing_blocks_without_the_flag_stop_before_any_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(cli, "labelled_swaps", _no_query)
    monkeypatch.setattr(bq_blocks, "fetch_blocks", _no_query)
    monkeypatch.setattr(bq_blocks, "fetch_bot_tx_logs", _no_query)
    with pytest.raises(SystemExit, match="--confirm-cost"):
        cli.run_step("fetch-blocks", False)


@pytest.mark.parametrize("fetched_for", [None, ["0xotherbot"]], ids=["missing", "stale"])
def test_bot_tx_logs_missing_or_stale_without_the_flag_stop_before_any_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fetched_for: list[str] | None
) -> None:
    (tmp_path / bq_blocks.BLOCKS_FILE).write_bytes(b"")
    if fetched_for is not None:  # logs on disk, but fetched for other bots
        (tmp_path / bq_blocks.OTHER_LOGS_FILE).write_bytes(b"")
        (tmp_path / bq_blocks.OTHER_LOGS_META).write_text(json.dumps({"bots": fetched_for}))
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(cli, "labelled_swaps", lambda: pl.DataFrame())
    monkeypatch.setattr(cli.flows, "top_bots", lambda swaps: ["0xbot"])
    monkeypatch.setattr(bq_blocks, "fetch_blocks", _no_query)
    monkeypatch.setattr(bq_blocks, "fetch_bot_tx_logs", _no_query)
    with pytest.raises(SystemExit, match="logs in top-bot transactions.*--confirm-cost"):
        cli.run_step("fetch-blocks", False)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["fetch-builders"], (False, False)),
        (["fetch-builders", "--dry-run"], (True, False)),
        (["fetch-builders", "--confirm-cost"], (False, True)),
    ],
)
def test_standalone_fetch_builders_passes_dry_run_and_the_flag(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: tuple[bool, bool]
) -> None:
    calls: list[tuple[bool, bool]] = []

    def fake(raw: Path, s: date, e: date, dry_run: bool, confirm_cost: bool) -> None:
        calls.append((dry_run, confirm_cost))

    monkeypatch.setattr(builders, "fetch_builders", fake)
    monkeypatch.setattr(sys, "argv", ["ulpe", *argv])
    cli.main()
    assert calls == [expected]
