from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest
from google.api_core.exceptions import NotFound

from uniswap_lp_economics import abi
from uniswap_lp_economics.config import NPM_ADDRESS, POOL_ADDRESS
from uniswap_lp_economics.data import history
from uniswap_lp_economics.events import MINT_TOPIC

ALICE = "0x" + "a1" * 20


def t_addr(a: str) -> str:
    return "0x" + abi.enc_addr(a)


def t_uint(v: int) -> str:
    return "0x" + abi.enc_uint(v)


def data(*values: int) -> str:
    return "0x" + "".join(abi.enc_int(v) for v in values)


def test_stage1_query_scans_both_contracts_and_seven_topics() -> None:
    q = history.build_stage1_query(date(2021, 5, 4), date(2026, 10, 1))
    assert f"'{POOL_ADDRESS}'" in q and f"'{NPM_ADDRESS}'" in q
    for t in (MINT_TOPIC, history.INCREASE_TOPIC, history.TRANSFER_TOPIC):
        assert t in q
    assert "TIMESTAMP('2021-05-04')" in q and "TIMESTAMP('2026-10-01')" in q


def test_npm_query_selects_tokens_minted_into_our_pool() -> None:
    q = history.build_npm_query("p.d.t")
    assert "`p.d.t`" in q
    assert history.INCREASE_TOPIC in q and history.TRANSFER_TOPIC in q
    assert "topics[SAFE_OFFSET(3)]" in q  # Transfer carries the token in its third indexed topic
    assert t_addr(NPM_ADDRESS) in q  # pool Mint owned by the position manager


@pytest.mark.parametrize(
    ("exists", "dry", "confirm", "expected"),
    [
        (True, False, False, "skip"),
        (False, True, False, "dry_run"),
        (False, False, False, "refuse"),
        (False, False, True, "run"),
        (False, True, True, "dry_run"),
    ],
)
def test_stage1_action(exists: bool, dry: bool, confirm: bool, expected: str) -> None:
    assert history.stage1_action(exists, dry, confirm) == expected


def test_is_billing_error() -> None:
    assert history.is_billing_error(RuntimeError("403 Billing has not been enabled"))
    assert history.is_billing_error(RuntimeError("Quota exceeded: free query bytes scanned"))
    assert not history.is_billing_error(RuntimeError("Syntax error"))


def test_decode_npm_events() -> None:
    inc = history.decode_npm_event([history.INCREASE_TOPIC, t_uint(7)], data(10**18, 5, 6))
    assert inc == {
        "event": "increase",
        "token_id": 7,
        "liquidity": 10**18,
        "amount0": 5,
        "amount1": 6,
    }
    col = history.decode_npm_event(
        [history.NPM_COLLECT_TOPIC, t_uint(7)],
        "0x" + abi.enc_addr(ALICE) + abi.enc_uint(3) + abi.enc_uint(4),
    )
    assert col == {
        "event": "npm_collect",
        "token_id": 7,
        "recipient": ALICE,
        "amount0": 3,
        "amount1": 4,
    }
    tr = history.decode_npm_event(
        [history.TRANSFER_TOPIC, t_addr("0x" + "00" * 20), t_addr(ALICE), t_uint(7)], "0x"
    )
    assert tr == {
        "event": "transfer",
        "from_owner": "0x" + "00" * 20,
        "to_owner": ALICE,
        "token_id": 7,
    }
    with pytest.raises(ValueError, match="unknown NonfungiblePositionManager topic"):
        history.decode_npm_event(["0x" + "00" * 32], "0x")


def test_load_history_decodes_both_files(tmp_path: Path) -> None:
    folder = tmp_path / history.HISTORY_DIR
    folder.mkdir()
    ts = datetime(2021, 6, 1, tzinfo=UTC)
    base = {"block_timestamp": ts, "transaction_hash": "0x01", "transaction_index": 0}
    pool = pl.DataFrame(
        [
            {
                **base,
                "block_number": 1,
                "log_index": 0,
                "address": POOL_ADDRESS,
                "topics": [
                    MINT_TOPIC,
                    t_addr(NPM_ADDRESS),
                    "0x" + abi.enc_int(-10),
                    "0x" + abi.enc_int(10),
                ],
                "data": "0x"
                + abi.enc_addr(NPM_ADDRESS)
                + abi.enc_uint(10**18)
                + abi.enc_uint(1)
                + abi.enc_uint(2),
            }
        ]
    )
    npm = pl.DataFrame(
        [
            {
                **base,
                "block_number": 1,
                "log_index": 1,
                "address": NPM_ADDRESS,
                "topics": [history.INCREASE_TOPIC, t_uint(7)],
                "data": data(10**18, 1, 2),
            }
        ]
    )
    pool.write_parquet(folder / history.POOL_FILE)
    npm.write_parquet(folder / history.NPM_FILE)
    p, n = history.load_history(tmp_path)
    assert p.row(0, named=True)["event"] == "mint" and p.row(0, named=True)["owner"] == NPM_ADDRESS
    assert p.row(0, named=True)["tx_hash"] == "0x01"
    assert n.row(0, named=True)["token_id"] == 7 and n.row(0, named=True)["tx_hash"] == "0x01"


def test_load_history_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ulpe fetch-history"):
        history.load_history(tmp_path)


class FakeClient:
    """Stands in for bigquery.Client: records every call, never touches the network."""

    def __init__(self, table_exists: bool) -> None:
        self.table_exists = table_exists
        self.queries: list[tuple[str, Any]] = []
        self.created_datasets = 0

    def get_table(self, table: str) -> object:
        if not self.table_exists:
            raise NotFound("no such table")
        return object()

    def query(self, sql: str, job_config: Any = None) -> object:
        self.queries.append((sql, job_config))
        return SimpleNamespace(total_bytes_processed=int(2.93e12))

    def create_dataset(self, *args: Any, **kwargs: Any) -> None:
        self.created_datasets += 1


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: FakeClient) -> None:
    monkeypatch.setattr(history.bigquery, "Client", lambda project=None: fake)


def test_stage1_refuses_without_confirm_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient(table_exists=False)
    _patch_client(monkeypatch, fake)
    with pytest.raises(SystemExit, match="--confirm-cost"):
        history.fetch_history(tmp_path, date(2021, 5, 4), date(2026, 10, 1), confirm_cost=False)
    # only the free dry-run estimate was issued: no destination table, no dataset, no files
    assert len(fake.queries) == 1 and fake.queries[0][1].dry_run is True
    assert fake.created_datasets == 0
    assert not (tmp_path / history.HISTORY_DIR).exists()


def test_dry_run_only_estimates_even_with_confirm_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient(table_exists=False)
    _patch_client(monkeypatch, fake)
    history.fetch_history(
        tmp_path, date(2021, 5, 4), date(2026, 10, 1), confirm_cost=True, dry_run=True
    )
    assert len(fake.queries) == 1 and fake.queries[0][1].dry_run is True
    assert fake.created_datasets == 0


def test_existing_history_skips_before_any_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / history.HISTORY_DIR
    folder.mkdir()
    (folder / history.POOL_FILE).write_bytes(b"")
    (folder / history.NPM_FILE).write_bytes(b"")

    def boom(project: str | None = None) -> None:
        raise AssertionError("no client may be created")

    monkeypatch.setattr(history.bigquery, "Client", boom)
    history.fetch_history(tmp_path, date(2021, 5, 4), date(2026, 10, 1), confirm_cost=False)
