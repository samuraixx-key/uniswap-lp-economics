import polars as pl
import pytest

from uniswap_lp_economics.lp.checks import check_r1_relays, check_r2_traces_vs_alchemy
from uniswap_lp_economics.lp.destination import (
    LIMITATION_TEXT,
    block_split,
    destination,
    searcher_costs,
)

MINER, PROPOSER, BOT = "0x" + "11" * 20, "0x" + "22" * 20, "0x" + "b0" * 20


def revenue() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "block_number": [1, 2],
            "miner": [MINER, MINER],
            "priority_wei": [6 * 10**17, 10**17],
            "direct_wei": [4 * 10**17, 0],
            "last_from": [MINER, "0x" + "33" * 20],
            "last_value_wei": [8 * 10**17, 5],
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


def test_block_split_payment_and_self_built() -> None:
    s = block_split(revenue())
    one, two = s.row(0, named=True), s.row(1, named=True)
    assert one["revenue_wei"] == 10**18 and one["payment_wei"] == 8 * 10**17
    assert one["proposer_share"] == pytest.approx(0.8) and not one["self_built"]
    assert two["self_built"] and two["proposer_share"] == pytest.approx(1.0)


def test_searcher_costs_and_destination_chain() -> None:
    aligned = pl.DataFrame(
        {
            "block_number": [1, 1],
            "log_index": [0, 1],
            "tx_hash": ["0xa", "0xb"],
            "flow_label": ["searcher", "searcher"],
            "notional_usd": [1000.0, 1000.0],
            "markout_usd_0": [10.0, 5.0],
            "p_cex_0": [2000.0, 2000.0],
            "protocol_fee_usd": [0.1, 0.1],
        }
    )
    events = pl.DataFrame(
        {
            "tx_hash": ["0xa", "0xb"],
            "block_number": [1, 1],
            "receipt_gas_used": [100_000, 100_000],
            "receipt_effective_gas_price": [3 * 10**9, 3 * 10**9],
        }
    )
    blocks = pl.DataFrame({"block_number": [1], "miner": [MINER], "base_fee_per_gas": [10**9]})
    direct = pl.DataFrame(
        {"tx_hash": ["0xa"], "direct_wei": [10**15]},
        schema={"tx_hash": pl.String, "direct_wei": pl.Int128},
    )
    other = pl.DataFrame({"tx_hash": ["0xa", "0xb"], "other_logs": [0, 2], "logs": [3, 9]})
    costs = searcher_costs(aligned, events, blocks, direct, other, block_split(revenue()))
    a = costs.filter(pl.col("tx_hash") == "0xa").row(0, named=True)
    paid_wei = 100_000 * 2 * 10**9 + 10**15  # priority + direct payment
    assert a["builder_paid_usd"] == pytest.approx(paid_wei / 1e18 * 2000.0)
    assert a["proposer_usd"] == pytest.approx(0.8 * a["builder_paid_usd"])
    assert a["burned_usd"] == pytest.approx(100_000 * 10**9 / 1e18 * 2000.0)
    assert a["kept_usd"] == pytest.approx(10.0 - a["burned_usd"] - a["builder_paid_usd"])
    assert costs.filter(pl.col("tx_hash") == "0xb")["scope"].item() == "multi_pool"
    steps = pl.DataFrame(
        {
            "flow_label": ["searcher", "searcher", "other"],
            "lvr_0": [12.0, 6.0, -1.0],
            "fee_usd": [1.5, 0.8, 0.2],
        }
    )
    d = destination(steps, aligned, costs)
    assert d["lvr_on_searcher_swaps_usd"] == 18.0 and d["lvr_on_other_flows_usd"] == -1.0
    assert d["pool_lvr_0_usd"] == 17.0
    assert d["searcher_gross_usd"] == 15.0 and d["multi_pool_gross_usd"] == 5.0
    single = (
        d["gas_burned_usd"] + d["builder_margin_usd"] + d["proposer_usd"] + d["searcher_kept_usd"]
    )
    assert single == pytest.approx(d["single_pool_gross_usd"])
    assert "last transaction from the fee recipient" in LIMITATION_TEXT


def test_flash_records_are_not_searcher_swaps() -> None:
    # A flash fee record (flow_label "flash", LVR 0) must stay out of the searcher totals.
    aligned = pl.DataFrame(
        {
            "block_number": [1],
            "log_index": [0],
            "tx_hash": ["0xa"],
            "flow_label": ["searcher"],
            "notional_usd": [1000.0],
            "markout_usd_0": [10.0],
            "p_cex_0": [2000.0],
            "protocol_fee_usd": [0.1],
        }
    )
    costs = pl.DataFrame(
        {"scope": ["single_pool"], "gross_usd": [10.0], "burned_usd": [1.0],
         "builder_paid_usd": [3.0], "builder_margin_usd": [1.0], "proposer_usd": [2.0],
         "kept_usd": [6.0], "other_logs": [0], "proposer_share": [0.5]}
    )  # fmt: skip
    steps = pl.DataFrame(
        {
            "flow_label": ["searcher", "flash"],
            "lvr_0": [12.0, 0.0],
            "fee_usd": [1.5, 7.0],
        }
    )
    d = destination(steps, aligned, costs)
    assert d["fees_on_searcher_swaps_usd"] == 1.5 and d["lvr_on_other_flows_usd"] == 0.0


def test_reported_checks_r1_and_r2() -> None:
    split = block_split(revenue())  # block 1 pays 8e17, self-built block 2 pays its 1e17
    relays = pl.DataFrame(
        {
            "block_number": [1, 2, 3, 9],
            "found": [True, True, False, True],
            "value_wei": [8 * 10**17, 10**17 + 5 * 10**14, None, 123],
        },
        schema={"block_number": pl.Int64, "found": pl.Boolean, "value_wei": pl.Int128},
    )
    r1 = check_r1_relays(relays, split)
    assert r1.passed  # reported, never gating
    assert r1.summary == {
        "sampled": 4,
        "found_on_a_relay": 3,  # counted before the join: block 9 is not in our split
        "compared_with_on_chain": 2,
        "match_within_1_wei": 1,
        "match_within_1pct": 2,
    }
    blocks = pl.DataFrame({"block_number": [1], "miner": [MINER], "base_fee_per_gas": [10**9]})
    transfers = pl.DataFrame(
        {
            "block_number": [1, 1, 1, 1],
            "tx_hash": ["0xa", "0xb", "0xc", "0xd"],
            "from_address": [BOT] * 4,
            "to_address": [MINER, MINER, PROPOSER, MINER],
            "value_wei": [10**15, 7, 99, 5 * 10**15],
        },
        schema={
            "block_number": pl.Int64,
            "tx_hash": pl.String,
            "from_address": pl.String,
            "to_address": pl.String,
            "value_wei": pl.Int128,
        },
    )
    direct = pl.DataFrame(
        {"tx_hash": ["0xa"], "direct_wei": [10**15]},
        schema={"tx_hash": pl.String, "direct_wei": pl.Int128},
    )
    pool = pl.DataFrame({"tx_hash": ["0xa", "0xb"]})  # 0xd is a bot payment outside our pool
    r2 = check_r2_traces_vs_alchemy(direct, transfers, blocks, pool)
    assert r2.summary == {"alchemy_pool_txs_with_payment": 2, "same_amount_in_traces": 1}


def test_shares_sum_to_one_when_the_identity_holds() -> None:
    # LVR on searcher steps (10) = LP fees (2) + protocol fees (1) + gross (7);
    # gross = multi-pool 2 + single-pool 5; single-pool = burned 1 + margin 1 + proposer 1 + kept 2.
    aligned = pl.DataFrame({"flow_label": ["searcher"], "protocol_fee_usd": [1.0]})
    costs = pl.DataFrame(
        {
            "scope": ["single_pool", "multi_pool"],
            "gross_usd": [5.0, 2.0],
            "burned_usd": [1.0, 0.5],
            "builder_paid_usd": [2.0, 0.5],
            "builder_margin_usd": [1.0, 0.25],
            "proposer_usd": [1.0, 0.25],
            "kept_usd": [2.0, 1.0],
            "other_logs": [0, 3],
            "proposer_share": [0.5, 0.5],
        }
    )
    steps = pl.DataFrame(
        {
            "flow_label": ["searcher", "other", "flash"],
            "lvr_0": [10.0, 4.0, 0.0],
            "fee_usd": [2.0, 0.5, 0.3],
        }
    )
    d = destination(steps, aligned, costs)
    assert d["pool_lvr_0_usd"] == 14.0 and d["lvr_on_other_flows_usd"] == 4.0
    assert d["share_searcher_of_pool_lvr"] == pytest.approx(10 / 14)
    assert d["share_fees"] == pytest.approx(0.2) and d["share_searcher_kept"] == pytest.approx(0.2)
    shares = [
        v for k, v in d.items() if k.startswith("share_") and k != "share_searcher_of_pool_lvr"
    ]
    assert len(shares) == 7 and sum(shares) == pytest.approx(1.0)


def test_searcher_costs_counts_its_fallbacks() -> None:
    aligned = pl.DataFrame(
        {
            "block_number": [1, 1, 9],
            "log_index": [0, 1, 0],
            "tx_hash": ["0xa", "0xb", "0xc"],
            "flow_label": ["searcher"] * 3,
            "notional_usd": [1000.0] * 3,
            "markout_usd_0": [1.0] * 3,
            "p_cex_0": [2000.0] * 3,
            "protocol_fee_usd": [0.0] * 3,
        }
    )
    # 0xc is in block 9 (not in the split) and has no receipt row; 0xb has no other-logs row
    events = pl.DataFrame(
        {
            "tx_hash": ["0xa", "0xb"],
            "block_number": [1, 1],
            "receipt_gas_used": [100_000] * 2,
            "receipt_effective_gas_price": [10**9] * 2,
        }
    )
    blocks = pl.DataFrame({"block_number": [1], "miner": [MINER], "base_fee_per_gas": [10**9]})
    direct = pl.DataFrame(schema={"tx_hash": pl.String, "direct_wei": pl.Int128})
    other = pl.DataFrame({"tx_hash": ["0xa", "0xc"], "other_logs": [0, 0], "logs": [1, 1]})
    costs = searcher_costs(aligned, events, blocks, direct, other, block_split(revenue()))
    steps = pl.DataFrame({"flow_label": ["searcher"], "lvr_0": [3.0], "fee_usd": [0.0]})
    d = destination(steps, aligned, costs)
    assert d["n_searcher_swaps"] == 3
    assert d["n_swaps_no_other_logs_row"] == 1  # 0xb: treated as multi-pool
    assert costs.filter(pl.col("tx_hash") == "0xb")["scope"].item() == "multi_pool"
    assert d["n_swaps_block_not_in_split"] == 1  # 0xc: proposer share 0
    assert d["n_swaps_null_costs"] == 1  # 0xc: no receipt, so no gas
