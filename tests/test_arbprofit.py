from typing import Any

import polars as pl
import pytest

from uniswap_lp_economics.arbprofit import (
    MULTI_POOL,
    SINGLE_POOL,
    add_costs,
    bot_profit_table,
    tx_scope,
    waterfall,
)
from uniswap_lp_economics.data.transfers import TRANSFER_SCHEMA

BOT = "0x" + "b0" * 20
USER = "0x" + "a1" * 20
ROUTER = "0x" + "c2" * 20
MINER = "0x" + "ee" * 20
GWEI = 10**9
SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "tx_hash": pl.String,
    "sender": pl.String,
    "flow_label": pl.String,
    "notional_usd": pl.Float64,
    "p_cex_0": pl.Float64,
    "receipt_gas_used": pl.Int64,
    "receipt_effective_gas_price": pl.Int64,
    "markout_usd_0": pl.Float64,
}
BLOCKS = pl.DataFrame(
    {"block_number": [1, 2], "miner": [MINER, MINER], "base_fee_per_gas": [20 * GWEI, 20 * GWEI]}
)


def aligned(rows: list[tuple[Any, ...]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=SCHEMA, orient="row")


def transfers(rows: list[tuple[int, str, str, str, int]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TRANSFER_SCHEMA, orient="row")


def costed() -> pl.DataFrame:
    a = aligned(
        [
            (1, "0xt1", BOT, "searcher", 100.0, 2000.0, 100_000, 30 * GWEI, 3.0),
            (1, "0xt1", BOT, "searcher", 300.0, 2000.0, 100_000, 30 * GWEI, 9.0),
            (2, "0xt2", BOT, "searcher", 50.0, 2000.0, 100_000, 30 * GWEI, 5.0),
            (2, "0xt3", ROUTER, "uniswap_router", 10.0, 2000.0, 100_000, 30 * GWEI, -1.0),
        ]
    )
    t = transfers(
        [
            (1, "0xt1", BOT, MINER, 10**16),  # 0.01 ETH to the fee recipient: 20 USD
            (1, "0xt1", BOT, USER, 10**18),  # not to the miner: ignored
        ]
    )
    scope = tx_scope(pl.DataFrame({"tx_hash": ["0xt1", "0xt2"], "other_logs": [0, 4]}))
    return add_costs(a, BLOCKS, t, scope, [BOT])


def test_costs_split_by_notional_within_tx() -> None:
    c = costed()
    # tx gas: 1e5 gas * 20 gwei base = 0.002 ETH = 4 USD burned; 1e5 * 10 gwei = 2 USD priority.
    assert c["gas_burned_usd"].to_list()[:2] == pytest.approx([1.0, 3.0])
    assert c["priority_fee_usd"].to_list()[:2] == pytest.approx([0.5, 1.5])
    assert c["coinbase_usd"].to_list()[:2] == pytest.approx([5.0, 15.0])
    assert c["gas_burned_usd"].to_list()[3] == pytest.approx(4.0)


def test_scope_and_coinbase_only_for_top_bots() -> None:
    c = costed()
    assert c["is_top_bot"].to_list() == [True, True, True, False]
    assert c["tx_scope"].to_list() == [SINGLE_POOL, SINGLE_POOL, MULTI_POOL, None]
    assert c["coinbase_usd"].to_list()[2:] == [0.0, None]


def test_zero_notional_tx_splits_equally() -> None:
    a = aligned(
        [
            (1, "0xt9", USER, "other_contract", 0.0, 2000.0, 100_000, 20 * GWEI, 0.0),
            (1, "0xt9", USER, "other_contract", 0.0, 2000.0, 100_000, 20 * GWEI, 0.0),
        ]
    )
    c = add_costs(
        a,
        BLOCKS,
        transfers([]),
        tx_scope(pl.DataFrame(schema={"tx_hash": pl.String, "other_logs": pl.Int64})),
        [],
    )
    assert c["gas_burned_usd"].to_list() == pytest.approx([2.0, 2.0])


def test_bot_profit_table_and_waterfall() -> None:
    c = costed()
    t = bot_profit_table(c)
    assert t["sender"].to_list() == [BOT, "TOTAL"]
    bot = t.row(0, named=True)
    assert bot["swaps"] == 2 and bot["gross_usd"] == pytest.approx(12.0)
    assert bot["kept_usd"] == pytest.approx(12.0 - 4.0 - 2.0 - 20.0)
    assert bot["builder_usd"] == pytest.approx(22.0)
    assert bot["multi_pool_swaps"] == 1 and bot["multi_pool_gross_usd"] == pytest.approx(5.0)
    assert bot["txs_with_coinbase"] == 1
    series = pl.DataFrame({"available_usd": [30.0, 10.0], "available_usd_cex1bp": [20.0, 5.0]})
    w = waterfall(series, c)
    assert w["available_usd"] == pytest.approx(40.0)
    assert w["captured_searchers_usd"] == pytest.approx(17.0)
    assert w["top_bot_single_pool_gross_usd"] == pytest.approx(12.0)
    assert w["kept_usd"] == pytest.approx(-14.0)


def test_bot_profit_table_without_bots() -> None:
    t = bot_profit_table(costed().with_columns(is_top_bot=pl.lit(False)))
    assert t["sender"].to_list() == ["TOTAL"]
    assert t["gross_usd"].item() == 0.0
