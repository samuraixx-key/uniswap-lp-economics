import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics.config import POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS
from uniswap_lp_economics.data.blocks import (
    bot_tx_logs_current,
    build_blocks_query,
    build_other_logs_query,
)

BOT1, BOT2, BOT3 = ("0x" + c * 40 for c in "123")
START, END = date(2026, 7, 1), date(2026, 10, 1)


def test_blocks_query_filters_partition_and_selects_fields() -> None:
    q = build_blocks_query(START, END)
    assert "timestamp >= TIMESTAMP('2026-07-01')" in q
    assert "timestamp < TIMESTAMP('2026-10-01')" in q
    for col in ("number", "miner", "base_fee_per_gas"):
        assert col in q


def test_other_logs_query_lists_bots_and_allowed_addresses() -> None:
    q = build_other_logs_query(START, END, [BOT1, BOT2])
    # Partition filters on both the transactions and the logs table.
    assert q.count("block_timestamp >= TIMESTAMP('2026-07-01')") == 2
    assert q.count("block_timestamp < TIMESTAMP('2026-10-01')") == 2
    assert f"'{BOT1}'" in q and f"'{BOT2}'" in q
    for addr in (POOL_ADDRESS, USDC_ADDRESS, WETH_ADDRESS):
        assert f"'{addr}'" in q


@pytest.mark.parametrize("bots", [[], ["0xABC' OR 1=1 --"], [BOT1.upper()]])
def test_other_logs_query_rejects_bad_bot_lists(bots: list[str]) -> None:
    with pytest.raises(ValueError):
        build_other_logs_query(START, END, bots)


def test_bot_tx_logs_current(tmp_path: Path) -> None:
    assert not bot_tx_logs_current(tmp_path, [BOT1])
    pl.DataFrame({"tx_hash": ["0x1"], "bot": [BOT1], "other_logs": [0], "logs": [3]}).write_parquet(
        tmp_path / "bot_tx_other_logs.parquet"
    )
    (tmp_path / "bot_tx_other_logs.json").write_text(json.dumps({"bots": [BOT1, BOT2]}))
    assert bot_tx_logs_current(tmp_path, [BOT1])
    assert bot_tx_logs_current(tmp_path, [BOT2, BOT1])
    assert not bot_tx_logs_current(tmp_path, [BOT1, BOT3])


@pytest.mark.live
def test_live_blocks_dry_run(tmp_path: Path) -> None:
    from uniswap_lp_economics.data.blocks import fetch_blocks

    assert fetch_blocks(tmp_path, date(2026, 9, 1), date(2026, 9, 2), dry_run=True) is None
