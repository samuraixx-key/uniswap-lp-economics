from datetime import date
from pathlib import Path

import polars as pl
import pyarrow as pa
import pytest
from google.cloud import bigquery

from uniswap_lp_economics.config import POOL_ADDRESS
from uniswap_lp_economics.data import builders

START, END = date(2026, 7, 1), date(2026, 10, 1)


def test_block_revenue_query_excludes_the_fee_recipients_own_transactions() -> None:
    q = builders.build_block_revenue_query(START, END)
    assert "t.from_address != b.miner" in q
    assert "x.status = 1" in q and "x.to_address = b.miner" in q
    assert "MAX(t.transaction_index)" in q  # the block's last transaction = the payment
    assert "TIMESTAMP('2026-07-01')" in q and "TIMESTAMP('2026-10-01')" in q


def test_pool_tx_queries_only_touch_pool_transactions() -> None:
    for q in (
        builders.build_tx_direct_query(START, END),
        builders.build_tx_other_logs_query(START, END),
    ):
        assert f"address = '{POOL_ADDRESS}'" in q


def test_wei_columns_parse_decimal_strings() -> None:
    df = pl.DataFrame({"a": ["123", None, "340282366920938463463374607431768211"]})
    out = builders.wei_columns(df, ["a"])
    assert out["a"].dtype == pl.Int128
    assert out["a"].to_list() == [123, 0, 340282366920938463463374607431768211]


def test_load_builders_names_the_command_when_a_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ulpe fetch-builders"):
        builders.load_builders(tmp_path)


def test_load_builders_round_trips_the_three_tables(tmp_path: Path) -> None:
    from uniswap_lp_economics.io import write_exact

    folder = tmp_path / builders.BUILDERS_DIR
    folder.mkdir()
    big = 10**30
    rev = pl.DataFrame(
        {
            "block_number": [1],
            "miner": ["0xaa"],
            "priority_wei": [big],
            "direct_wei": [0],
            "last_from": ["0xbb"],
            "last_value_wei": [5],
        },
        schema={
            "block_number": pl.Int64,
            "miner": pl.String,
            "priority_wei": pl.Int128,
            "direct_wei": pl.Int128,
            "last_from": pl.String,
            "last_value_wei": pl.Int128,
        },
    )
    direct = pl.DataFrame(
        {"tx_hash": ["0x1"], "direct_wei": [7]}, schema_overrides={"direct_wei": pl.Int128}
    )
    other = pl.DataFrame({"tx_hash": ["0x1"], "other_logs": [2], "logs": [5]})
    write_exact(rev, folder / builders.BLOCK_REVENUE)
    write_exact(direct, folder / builders.TX_DIRECT)
    write_exact(other, folder / builders.TX_OTHER_LOGS)
    r, d, o = builders.load_builders(tmp_path)
    assert r["priority_wei"].dtype == pl.Int128 and r["priority_wei"][0] == big
    assert d["direct_wei"][0] == 7 and o["other_logs"][0] == 2


class FakeJob:
    def __init__(self, table: pa.Table | None = None, scanned: int = 0) -> None:
        self.total_bytes_processed = scanned
        self._table = table

    def result(self) -> "FakeJob":
        return self

    def to_arrow(self) -> pa.Table:
        assert self._table is not None
        return self._table


class FakeClient:
    """Stands in for bigquery.Client: records queries, never touches the network."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.dry: list[str] = []
        self.paid: list[tuple[str, int | None]] = []
        self.fail = fail
        self.scanned = 2_000_000_000

    def query(self, query: str, job_config: bigquery.QueryJobConfig) -> FakeJob:
        if job_config.dry_run:
            self.dry.append(query)
            return FakeJob(scanned=self.scanned)
        if self.fail is not None:
            raise self.fail
        self.paid.append((query, job_config.maximum_bytes_billed))
        if "AS priority_wei" in query:
            return FakeJob(
                pa.table(
                    {
                        "block_number": [1, 2],
                        "miner": ["0xaa", "0xaa"],
                        "priority_wei": ["10", None],
                        "direct_wei": [None, "30000000000000000000"],
                        "last_from": ["0xbb", None],
                        "last_value_wei": ["5", None],
                    }
                )
            )
        if "AS direct_wei" in query:
            return FakeJob(pa.table({"tx_hash": ["0x1"], "direct_wei": ["7"]}))
        return FakeJob(pa.table({"tx_hash": ["0x1"], "other_logs": [2], "logs": [5]}))


def test_fetch_builders_writes_three_typed_tables_then_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(builders.bigquery, "Client", lambda project: fake)
    builders.fetch_builders(tmp_path, START, END)
    assert len(fake.paid) == 3
    assert all(cap == builders.MAX_GB_BILLED * 10**9 for _, cap in fake.paid)
    rev, direct, other = builders.load_builders(tmp_path)
    assert rev.schema["block_number"] == pl.Int64
    assert rev["priority_wei"].to_list() == [10, 0]  # nulls become 0
    assert rev["direct_wei"].to_list() == [0, 30 * 10**18]
    assert direct["direct_wei"].to_list() == [7]
    assert other.schema["other_logs"] == pl.Int64 and other["logs"].to_list() == [5]
    assert not list((tmp_path / builders.BUILDERS_DIR).glob("*.part"))
    builders.fetch_builders(tmp_path, START, END)
    assert len(fake.paid) == 3  # existing files are not re-queried


def test_fetch_builders_dry_run_runs_no_paid_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(builders.bigquery, "Client", lambda project: fake)
    builders.fetch_builders(tmp_path, START, END, dry_run=True)
    assert len(fake.dry) == 3 and fake.paid == []
    assert not list((tmp_path / builders.BUILDERS_DIR).glob("*.parquet"))


def test_fetch_builders_turns_a_billing_error_into_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient(fail=RuntimeError("Billing has not been enabled"))
    monkeypatch.setattr(builders.bigquery, "Client", lambda project: fake)
    with pytest.raises(SystemExit, match="billing"):
        builders.fetch_builders(tmp_path, START, END)


def test_trace_payments_exclude_the_fee_recipients_own_transactions() -> None:
    for q in (
        builders.build_block_revenue_query(START, END),
        builders.build_tx_direct_query(START, END),
    ):
        assert "JOIN t ON t.`hash` = x.transaction_hash" in q
        assert "t.from_address != b.miner" in q and "x.to_address = b.miner" in q
        assert "x.call_type NOT IN ('delegatecall', 'callcode', 'staticcall')" in q
        assert "x.call_type IS NULL" in q
    assert "`hash`, block_number" in builders.build_block_revenue_query(START, END)
    assert "SELECT `hash`, from_address" in builders.build_tx_direct_query(START, END)


def test_other_logs_target_falls_back_to_the_created_contract() -> None:
    q = builders.build_tx_other_logs_query(START, END)
    assert "COALESCE(to_address, receipt_contract_address) AS target" in q
    assert "l.address != t.target" in q


def test_an_oversized_estimate_stops_before_any_paid_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    fake.scanned = (builders.MAX_GB_BILLED + 1) * 10**9
    monkeypatch.setattr(builders.bigquery, "Client", lambda project: fake)
    with pytest.raises(SystemExit, match="cap"):
        builders.fetch_builders(tmp_path, START, END)
    assert fake.paid == []
    assert not list((tmp_path / builders.BUILDERS_DIR).glob("*.parquet"))


def test_dry_run_reports_an_oversized_estimate_without_stopping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeClient()
    fake.scanned = (builders.MAX_GB_BILLED + 1) * 10**9
    monkeypatch.setattr(builders.bigquery, "Client", lambda project: fake)
    builders.fetch_builders(tmp_path, START, END, dry_run=True)
    assert len(fake.dry) == 3 and "WARNING" in capsys.readouterr().out
