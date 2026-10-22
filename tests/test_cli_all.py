import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics import cli, config
from uniswap_lp_economics.data import bigquery, builders, history, relays
from uniswap_lp_economics.data import blocks as bq_blocks


def test_all_runs_every_step_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(cli, "run_step", lambda name, confirm_cost: ran.append(name) or "PASS")
    monkeypatch.setattr(sys, "argv", ["ulpe", "all", "--confirm-cost"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    assert ran == list(cli.ALL_STEPS)
    assert ran[-1] == "figures" and ran.index("lp") < ran.index("figures")
    assert ran.index("fetch-relays") + 1 == ran.index("fetch-timing") < ran.index("lp")
    assert ran.index("fetch-timing") + 1 == ran.index("fetch-paths") < ran.index("lp")
    assert ran.index("fetch-builders") + 1 == ran.index("fetch-payout-code")
    assert ran.index("fetch-payout-code") + 1 == ran.index("fetch-relays")
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
    (folder / builders.LAST_TX).write_bytes(b"")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(builders, "fetch_builders", _no_query)
    assert cli.run_step("fetch-builders", False) == "OK"


def test_a_missing_last_tx_table_is_not_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / builders.BUILDERS_DIR
    folder.mkdir()
    for name in (builders.BLOCK_REVENUE, builders.TX_DIRECT, builders.TX_OTHER_LOGS):
        (folder / name).write_bytes(b"")  # the three old tables, no last_tx.parquet
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(builders, "fetch_builders", _no_query)
    with pytest.raises(SystemExit, match="--confirm-cost"):
        cli.run_step("fetch-builders", False)
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(builders, "fetch_builders", lambda *a, **k: calls.append(a))
    assert cli.run_step("fetch-builders", True) == "OK"
    assert len(calls) == 1


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


def test_standalone_fetch_logs_without_the_flag_stops_before_any_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(bigquery, "raw_logs_path", lambda s, e: tmp_path / f"{s}_{e}.parquet")
    monkeypatch.setattr(bigquery, "fetch_pool_logs", _no_query)
    argv = ["ulpe", "fetch-logs", "--start", "2026-07-01", "--end", "2026-08-01"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match=r"ulpe fetch-logs .*--confirm-cost"):
        cli.main()


@pytest.mark.parametrize("flag", ["--dry-run", "--confirm-cost"])
def test_standalone_fetch_logs_queries_with_dry_run_or_the_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flag: str
) -> None:
    calls: list[tuple[date, bool]] = []
    monkeypatch.setattr(bigquery, "raw_logs_path", lambda s, e: tmp_path / f"{s}_{e}.parquet")
    monkeypatch.setattr(
        bigquery, "fetch_pool_logs", lambda s, e, dry_run=False: calls.append((s, dry_run))
    )
    argv = ["ulpe", "fetch-logs", "--start", "2026-07-01", "--end", "2026-08-01", flag]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert calls == [(date(2026, 7, 1), flag == "--dry-run")]


def test_standalone_fetch_blocks_without_the_flag_stops_before_any_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(cli, "labelled_swaps", _no_query)
    monkeypatch.setattr(bq_blocks, "fetch_blocks", _no_query)
    monkeypatch.setattr(bq_blocks, "fetch_bot_tx_logs", _no_query)
    monkeypatch.setattr(sys, "argv", ["ulpe", "fetch-blocks"])
    with pytest.raises(SystemExit, match=r"ulpe fetch-blocks --confirm-cost"):
        cli.main()


def test_chain_state_skips_the_position_build_when_everything_is_on_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from uniswap_lp_economics.data import chain_state

    (tmp_path / "snapshot_meta.json").write_text(json.dumps({"block": 1}))
    folder = tmp_path / chain_state.CHAIN_DIR
    folder.mkdir()
    for name in (
        chain_state.SNAPSHOT_FEES,
        chain_state.SAMPLE_FEES,
        chain_state.START_POSITIONS,
        chain_state.END_POSITIONS,
        chain_state.OWNER_CODE,
    ):
        (folder / name).write_bytes(b"")
    hist = tmp_path / history.HISTORY_DIR / history.POOL_FILE
    hist.parent.mkdir(parents=True)
    hist.write_bytes(b"")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(cli, "_rpc", lambda: None)
    monkeypatch.setattr(cli, "build_positions", lambda *a: pytest.fail("built positions"))
    cli.fetch_chain_state()


def test_the_holdout_waits_for_the_last_tx_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pl.DataFrame({"block_number": [1, 2]}).write_parquet(tmp_path / bq_blocks.BLOCKS_FILE)
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(cli.relays, "fetch_relay_sample", lambda *a: None)
    monkeypatch.setattr(cli.relays, "retry_unchecked", lambda *a, **kw: 0)
    monkeypatch.setattr(cli.relays, "fetch_holdout", lambda *a: pytest.fail("drew a holdout"))
    cli.fetch_relays()
    assert "fetch-builders" in capsys.readouterr().out


def test_fetch_relays_retries_only_holdout2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pl.DataFrame({"block_number": [1, 2]}).write_parquet(tmp_path / bq_blocks.BLOCKS_FILE)
    (tmp_path / builders.BUILDERS_DIR).mkdir()
    (tmp_path / builders.BUILDERS_DIR / builders.LAST_TX).write_bytes(b"")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(cli, "_block_classes", lambda: "classes")
    monkeypatch.setattr(cli.relays, "fetch_relay_sample", lambda *a: None)
    holdouts: list[dict[str, object]] = []
    monkeypatch.setattr(cli.relays, "fetch_holdout", lambda *a, **kw: holdouts.append(kw))
    retried: list[dict[str, object]] = []
    monkeypatch.setattr(cli.relays, "retry_unchecked", lambda *a, **kw: retried.append(kw) or 0)
    cli.fetch_relays()
    assert holdouts == [
        {},
        {"seed": 45, "holdout_file": "relay_holdout_2.parquet", "round_label": "holdout2"},
    ]
    assert retried == [{"rounds": ("holdout2",)}]


def test_fetch_paths_targets_paid_and_payout_holdout2_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(cli, "_rpc", lambda: "rpc")
    got: list[pl.DataFrame] = []
    monkeypatch.setattr(cli.transfers, "fetch_payment_paths", lambda c, d, t: got.append(t))
    cli.fetch_paths()  # no seed-45 draw yet: nothing to do
    assert got == []
    pl.DataFrame(
        {"block_number": [1, 2, 3, 4], "stratum": ["payout"] * 4, "seed": [45] * 4}
    ).write_parquet(tmp_path / relays.HOLDOUT2_FILE)
    classes = pl.DataFrame(
        {
            "block_number": [1, 2, 3, 4, 5],
            "cls": ["paid", "payout", "proposer_is_fee_recipient", "unexplained", "payout"],
            "to_address": ["0xa", "0xb", None, "0xd", "0xe"],
            "last_value_wei": [1, 2, 3, 4, 5],
        },
        schema_overrides={"last_value_wei": pl.Int128},
    )
    monkeypatch.setattr(cli, "_block_classes", lambda: classes)
    cli.fetch_paths()
    assert got[0]["block_number"].to_list() == [1, 2]
    assert got[0].columns == ["block_number", "to_address", "last_value_wei"]
