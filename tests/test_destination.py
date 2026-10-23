import json
from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics.data.relays import HOLDOUT2_FILE, HOLDOUT2_RETRIED, HOLDOUT2_ROUND
from uniswap_lp_economics.data.transfers import PATH_SCHEMA
from uniswap_lp_economics.io import write_exact
from uniswap_lp_economics.lp.checks import (
    HOLDOUT2_DECISION_FILE,
    HOLDOUT_BAR,
    HOLDOUT_DECISION_FILE,
    check_r1_relays,
    check_r2_traces_vs_alchemy,
    check_r3_lp_types,
    holdout2_ready,
    holdout_decision,
    paths_complete,
    settle_decision,
)
from uniswap_lp_economics.lp.destination import (
    LIMITATION_TEXT,
    LIMITATION_TEXT_HEDGE,
    block_split,
    class_table,
    destination,
    paid_block_ratio,
    searcher_costs,
)
from uniswap_lp_economics.lp.payouts import (
    EMPTY,
    PAID,
    PAYOUT,
    PROPOSER_IS_FEE_RECIPIENT,
    UNEXPLAINED,
    block_classes,
)

MINER, PROPOSER, BOT = "0x" + "11" * 20, "0x" + "22" * 20, "0x" + "b0" * 20
NO_USD = pl.DataFrame(schema={"block_number": pl.Int64, "builder_paid_usd": pl.Float64})
_ZERO = {
    "sampled": 0,
    "found": 0,
    "match_within_1_wei": 0,
    "match_within_1pct": 0,
    "recipient_match": 0,
    "recipient_compared": 0,
}


def _split(rev: pl.DataFrame, payouts: bool = False) -> pl.DataFrame:
    """block_split with classes built from the revenue frame; every transaction goes to 0xee."""
    txs = rev.filter(pl.col("last_from").is_not_null())
    last_tx = txs.select(
        "block_number",
        to_address=pl.lit("0x" + "ee" * 20),
        receipt_gas_used=pl.lit(21000, dtype=pl.Int64),
    )
    return block_split(rev, block_classes(rev, last_tx), payouts=payouts)


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
    s = _split(revenue())
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
    costs = searcher_costs(aligned, events, blocks, direct, other, _split(revenue()))
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
    d = destination(steps, aligned, costs, _split(revenue()), sensitivity=True)
    assert d["lvr_on_searcher_swaps_usd"] == 18.0 and d["lvr_on_other_flows_usd"] == -1.0
    assert d["pool_lvr_0_usd"] == 17.0
    assert d["searcher_gross_usd"] == 15.0 and d["multi_pool_gross_usd"] == 5.0
    single = (
        d["gas_burned_usd"] + d["builder_margin_usd"] + d["proposer_usd"] + d["searcher_kept_usd"]
    )
    assert single == pytest.approx(d["single_pool_gross_usd"])
    assert "last transaction, sent by the fee recipient" in LIMITATION_TEXT
    assert "last transaction from the fee recipient" in LIMITATION_TEXT_HEDGE
    assert "sensitivity_self_built" not in destination(
        steps, aligned, costs, _split(revenue()), sensitivity=False
    )


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
         "kept_usd": [6.0], "other_logs": [0], "proposer_share": [0.5], "self_built": [False]}
    )  # fmt: skip
    steps = pl.DataFrame(
        {
            "flow_label": ["searcher", "flash"],
            "lvr_0": [12.0, 0.0],
            "fee_usd": [1.5, 7.0],
        }
    )
    d = destination(steps, aligned, costs, _split(revenue()), sensitivity=True)
    assert d["fees_on_searcher_swaps_usd"] == 1.5 and d["lvr_on_other_flows_usd"] == 0.0


def test_reported_checks_r1_and_r2() -> None:
    split = _split(revenue())  # block 1 pays 8e17, block 2 (class 5) is built for its 1e17
    relays = pl.DataFrame(
        {
            "block_number": [1, 2, 3, 9],
            "found": [True, True, False, True],
            "value_wei": [8 * 10**17, 10**17 + 5 * 10**14, None, 123],
        },
        schema={"block_number": pl.Int64, "found": pl.Boolean, "value_wei": pl.Int128},
    )
    r1 = check_r1_relays(relays, split, NO_USD)
    assert r1.passed  # reported, never gating
    s = r1.summary
    assert (s["sampled"], s["found_on_a_relay"], s["compared_with_on_chain"]) == (4, 3, 2)
    assert (s["match_within_1_wei"], s["match_within_1pct"]) == (1, 2)
    assert s["not_found_unchecked"] is None and s["not_found_none_unchecked"] is None
    seen = s["by_round"]["seen"]  # a file with no round column: everything is seen
    assert seen[PAID] == {
        **_ZERO,
        "sampled": 1,
        "found": 1,
        "match_within_1_wei": 1,
        "match_within_1pct": 1,
    }
    assert seen[UNEXPLAINED] == {**_ZERO, "sampled": 1, "found": 1, "match_within_1pct": 1}
    assert s["by_round"]["holdout"][PAID] == _ZERO
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
            "self_built": [False, False],
        }
    )
    steps = pl.DataFrame(
        {
            "flow_label": ["searcher", "other", "flash"],
            "lvr_0": [10.0, 4.0, 0.0],
            "fee_usd": [2.0, 0.5, 0.3],
        }
    )
    d = destination(steps, aligned, costs, _split(revenue()), sensitivity=True)
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
    costs = searcher_costs(aligned, events, blocks, direct, other, _split(revenue()))
    steps = pl.DataFrame({"flow_label": ["searcher"], "lvr_0": [3.0], "fee_usd": [0.0]})
    d = destination(steps, aligned, costs, _split(revenue()), sensitivity=True)
    assert d["n_searcher_swaps"] == 3
    assert d["n_swaps_no_other_logs_row"] == 1  # 0xb: treated as multi-pool
    assert costs.filter(pl.col("tx_hash") == "0xb")["scope"].item() == "multi_pool"
    assert d["n_swaps_block_not_in_split"] == 1  # 0xc: proposer share 0
    assert d["n_swaps_null_costs"] == 1  # 0xc: no receipt, so no gas


def test_r1_counts_not_found_blocks_by_relay_coverage() -> None:
    split = _split(revenue())
    relays = pl.DataFrame(
        {
            "block_number": [1, 2, 3, 4],
            "found": [True, False, False, False],
            "value_wei": [8 * 10**17, None, None, None],
            "proposer_fee_recipient": [PROPOSER, None, None, None],
            "relays_unchecked": [None, "https://a,https://b", None, "https://a"],
        },
        schema={
            "block_number": pl.Int64,
            "found": pl.Boolean,
            "value_wei": pl.Int128,
            "proposer_fee_recipient": pl.String,
            "relays_unchecked": pl.String,
        },
    )
    r1 = check_r1_relays(relays, split, NO_USD)
    assert r1.summary["not_found_unchecked"] == 2
    assert r1.summary["not_found_none_unchecked"] == 1
    paid = r1.summary["by_round"]["seen"][PAID]
    # PROPOSER is not the last transaction's to_address (0xee): compared, not matched.
    assert paid == {
        **_ZERO,
        "sampled": 1,
        "found": 1,
        "match_within_1_wei": 1,
        "match_within_1pct": 1,
        "recipient_compared": 1,
    }


def _world(rows: list[tuple]) -> tuple[pl.DataFrame, pl.DataFrame]:
    """(relays, split) from (block, round, cls, relay value, on-chain payment, relay recipient,
    to_address) rows, every block found on relay 'r'. The fee recipient is MINER."""
    n = len(rows)
    relays = pl.DataFrame(
        {
            "block_number": [r[0] for r in rows],
            "relay": ["r"] * n,
            "found": [True] * n,
            "value_wei": [r[3] for r in rows],
            "proposer_fee_recipient": [r[5] for r in rows],
            "relays_unchecked": [None] * n,
            "round": [r[1] for r in rows],
        },
        schema={
            "block_number": pl.Int64,
            "relay": pl.String,
            "found": pl.Boolean,
            "value_wei": pl.Int128,
            "proposer_fee_recipient": pl.String,
            "relays_unchecked": pl.String,
            "round": pl.String,
        },
    )
    split = pl.DataFrame(
        {
            "block_number": [r[0] for r in rows],
            "miner": [MINER] * n,
            "payment_wei": [r[4] for r in rows],
            "cls": [r[2] for r in rows],
            "to_address": [r[6] for r in rows],
        },
        schema={
            "block_number": pl.Int64,
            "miner": pl.String,
            "payment_wei": pl.Int128,
            "cls": pl.String,
            "to_address": pl.String,
        },
    )
    return relays, split


def _twenty(off_value: int = 0, off_recipient: int = 0) -> list[tuple]:
    """20 found holdout payout blocks; the first `off_value` are 5 wei off the relay, the first
    `off_recipient` pay someone other than the relay's recipient."""
    return [
        (
            i,
            "holdout",
            PAYOUT,
            10**18 + (5 if i < off_value else 0),
            10**18,
            BOT if i < off_recipient else PROPOSER,
            PROPOSER,
        )
        for i in range(20)
    ]


def test_decision_passes_at_95_percent_on_both() -> None:
    d = holdout_decision(*_world(_twenty(off_value=1, off_recipient=1)))  # 19 of 20 on each
    assert d["n_found_payout"] == 20 and d["bar"] == HOLDOUT_BAR == 0.95
    assert d["share_within_1_wei"] == pytest.approx(0.95)
    assert d["share_recipient_match"] == pytest.approx(0.95)
    assert d["share_within_1pct"] == 1.0 and d["one_split"] is True


def test_decision_fails_below_the_bar_on_either() -> None:
    assert holdout_decision(*_world(_twenty(off_value=2)))["one_split"] is False  # 18/20 exact
    assert holdout_decision(*_world(_twenty(off_recipient=2)))["one_split"] is False  # 18/20 paid
    no_recipient = [(*r[:5], None, r[6]) for r in _twenty()]
    d = holdout_decision(*_world(no_recipient))  # no relay recipient counts as a failure
    assert d["share_recipient_match"] == 0.0 and d["one_split"] is False


def test_decision_with_no_found_payout_blocks_is_hedge() -> None:
    relays, split = _world([(1, "seen", PAYOUT, 10**18, 10**18, PROPOSER, PROPOSER)])
    d = holdout_decision(relays, split)
    assert d["n_found_payout"] == 0 and d["one_split"] is False
    assert d["share_within_1_wei"] is None
    # a relay file with no round column at all is the same
    assert holdout_decision(relays.drop("round"), split)["one_split"] is False


def test_only_holdout_payout_rows_decide() -> None:
    noise = [
        (100, "seen", PAYOUT, 1, 10**18, BOT, PROPOSER),
        (101, "retry", PAYOUT, 1, 10**18, BOT, PROPOSER),
        (102, "holdout", PAID, 1, 10**18, BOT, PROPOSER),
        (103, "holdout", UNEXPLAINED, 1, 10**18, BOT, PROPOSER),
    ]
    d = holdout_decision(*_world(_twenty() + noise))
    assert d["n_found_payout"] == 20 and d["one_split"] is True
    assert d["share_within_1_wei"] == 1.0 and d["share_recipient_match"] == 1.0


def test_recipient_match_ignores_address_case() -> None:
    mixed = "0xAbC" + "d" * 37
    relays, split = _world([(1, "holdout", PAYOUT, 10**18, 10**18, mixed, mixed.lower())])
    assert holdout_decision(relays, split)["share_recipient_match"] == 1.0
    part = check_r1_relays(relays, split, NO_USD).summary["by_round"]["holdout"][PAYOUT]
    assert part["recipient_match"] == 1 and part["recipient_compared"] == 1


def test_r1_by_round_stratum_failures_and_unexplained_relays() -> None:
    relays, split = _world(
        [
            (1, "seen", PAID, 10**18, 10**18, PROPOSER, PROPOSER),
            (2, "retry", UNEXPLAINED, 10**18, 10**18, PROPOSER, PROPOSER),
            (3, "holdout", PAYOUT, 10**18, 10**18, BOT, PROPOSER),  # R1b failure
            (4, "holdout", PAYOUT, 10**18, 10**18, PROPOSER, PROPOSER),
            (5, "holdout", UNEXPLAINED, 7, 10**18, None, PROPOSER),
        ]
    )
    unfound = pl.DataFrame(  # unfound unexplained blocks name the relays that gave no answer
        {
            "block_number": [6, 7],
            "relay": [None, None],
            "found": [False, False],
            "value_wei": [None, None],
            "proposer_fee_recipient": [None, None],
            "relays_unchecked": ["x,y", "x"],
            "round": ["retry", None],
        },
        schema=relays.schema,
    )
    extra = split.head(2).with_columns(block_number=pl.Series([6, 7]), cls=pl.lit(UNEXPLAINED))
    s = check_r1_relays(pl.concat([relays, unfound]), pl.concat([split, extra]), NO_USD).summary
    br = s["by_round"]
    assert br["seen"][PAID]["found"] == 1 and br["seen"][UNEXPLAINED]["sampled"] == 1  # block 7
    assert br["retry"][UNEXPLAINED]["sampled"] == 2 and br["retry"][UNEXPLAINED]["found"] == 1
    assert br["holdout"][PAYOUT]["recipient_match"] == 1 and br["holdout"][PAYOUT]["found"] == 2
    st = s["holdout_by_stratum"]
    assert st["payout"]["sampled"] == 2 and st["rest"]["sampled"] == 1
    assert st["rest"]["match_within_1_wei"] == 0 and st["rest"]["match_within_1pct"] == 0
    assert s["holdout_recipient_failures"] == [
        {"block_number": 3, "to_address": PROPOSER, "proposer_fee_recipient": BOT}
    ]
    assert s["unexplained_by_relay"] == {  # blocks 2 and 5 found on r; 6 and 7 unanswered
        "seen": {"delivered": {}, "unchecked": {"x": 1}},
        "retry": {"delivered": {"r": 1}, "unchecked": {"x": 1, "y": 1}},
        "holdout": {"delivered": {"r": 1}, "unchecked": {}},
        "holdout2": {"delivered": {}, "unchecked": {}},
    }
    # top-level counts: the original sample only (seen, retry, null), never holdout rows
    assert (s["sampled"], s["found_on_a_relay"]) == (4, 2)


def _unfound(
    blocks: list[int], round_: str, unchecked: str | None, like: pl.DataFrame
) -> pl.DataFrame:
    n = len(blocks)
    return pl.DataFrame(
        {
            "block_number": blocks,
            "relay": [None] * n,
            "found": [False] * n,
            "value_wei": [None] * n,
            "proposer_fee_recipient": [None] * n,
            "relays_unchecked": [unchecked] * n,
            "round": [round_] * n,
        },
        schema=like.schema,
    )


def test_recipient_failures_list_every_round_but_the_decision_uses_the_holdout() -> None:
    relays, split = _world(
        [
            (1, "seen", PAYOUT, 10**18, 10**18, BOT, PROPOSER),  # fails R1b
            (2, "retry", PAYOUT, 10**18, 10**18, PROPOSER, PROPOSER),  # passes
            (3, "holdout", PAYOUT, 10**18, 10**18, BOT, PROPOSER),  # fails R1b
            (4, "seen", PAID, 10**18, 10**18, BOT, PROPOSER),  # not class 3
            (5, "seen", PAYOUT, 10**18, 10**18, None, PROPOSER),  # no relay recipient: fails
        ]
    )
    lost = _unfound([6], "seen", None, relays)  # not found: nothing to compare
    extra = split.head(1).with_columns(block_number=pl.Series([6]))
    s = check_r1_relays(pl.concat([relays, lost]), pl.concat([split, extra]), NO_USD).summary
    assert s["recipient_failures"] == [
        {"round": "seen", "block_number": 1, "to_address": PROPOSER, "proposer_fee_recipient": BOT},
        {
            "round": "holdout",
            "block_number": 3,
            "to_address": PROPOSER,
            "proposer_fee_recipient": BOT,
        },
        {
            "round": "seen",
            "block_number": 5,
            "to_address": PROPOSER,
            "proposer_fee_recipient": None,
        },
    ]
    assert [r["block_number"] for r in s["holdout_recipient_failures"]] == [3]


def test_holdout_by_stratum_counts_unanswered_blocks() -> None:
    relays, split = _world([(1, "holdout", PAYOUT, 10**18, 10**18, PROPOSER, PROPOSER)])
    lost = pl.concat(
        [
            _unfound([2, 3], "holdout", "x", relays),
            _unfound([4], "holdout", None, relays),  # every relay answered: not unchecked
            _unfound([5], "retry", "x", relays),  # not a holdout row
        ]
    )
    rows = [(2, PAYOUT), (3, "paid"), (4, PAYOUT), (5, PAYOUT)]
    extra = pl.concat(
        [
            split.head(1).with_columns(block_number=pl.lit(b, dtype=pl.Int64), cls=pl.lit(c))
            for b, c in rows
        ]
    )
    st = check_r1_relays(pl.concat([relays, lost]), pl.concat([split, extra]), NO_USD).summary[
        "holdout_by_stratum"
    ]
    assert (st["payout"]["sampled"], st["payout"]["found"], st["payout"]["unchecked"]) == (3, 1, 1)
    assert (st["rest"]["sampled"], st["rest"]["unchecked"]) == (1, 1)


def test_unknown_relay_recipient_is_no_recipient() -> None:
    # rows fetched before the fix stored "none" or "" for a missing recipient
    rows = [(i, "seen", PAYOUT, 10**18, 10**18, r, PROPOSER) for i, r in enumerate(["none", ""])]
    rows += [(9, "seen", PAID, 10**18, 10**18, "none", PROPOSER)]
    rows += [(10, "seen", PROPOSER_IS_FEE_RECIPIENT, 10**18, 10**18, "none", MINER)]
    relays, split = _world(rows)
    s = check_r1_relays(relays, split, NO_USD).summary
    assert s["by_round"]["seen"][PAYOUT]["recipient_compared"] == 0
    assert s["by_round"]["seen"][PAID]["recipient_compared"] == 0
    assert s["r1c_breaking_blocks"] == []  # "none" is not a recipient that differs from the miner
    assert [r["proposer_fee_recipient"] for r in s["recipient_failures"]] == [None, None]


def test_unfound_holdout_payout_row_does_not_decide() -> None:
    relays, split = _world(_twenty())
    lost = _unfound([500], "holdout", "x", relays)
    extra = split.head(1).with_columns(
        block_number=pl.Series([500]), payment_wei=pl.lit(0, dtype=pl.Int128)
    )
    d = holdout_decision(pl.concat([relays, lost]), pl.concat([split, extra]))
    assert d == holdout_decision(relays, split)
    assert d["n_found_payout"] == 20 and d["one_split"] is True


def test_r1c_lists_fee_recipient_blocks_delivered_for_someone_else() -> None:
    cls = PROPOSER_IS_FEE_RECIPIENT
    relays, split = _world(
        [
            (1, "seen", cls, 5, 5, MINER, MINER),  # delivered to the fee recipient itself: fine
            (2, "seen", cls, 5, 5, PROPOSER, MINER),  # delivered for someone else: breaks the class
            (3, "seen", cls, 5, 5, PROPOSER, MINER),
            (4, "seen", PAID, 5, 5, PROPOSER, MINER),  # other classes are not R1c
        ]
    )
    usd = pl.DataFrame(
        {"block_number": [2, 2, 4], "builder_paid_usd": [1.5, 2.0, 99.0]},
        schema={"block_number": pl.Int64, "builder_paid_usd": pl.Float64},
    )
    got = check_r1_relays(relays, split, usd).summary["r1c_breaking_blocks"]
    assert got == [
        {"block_number": 2, "builder_paid_usd": 3.5},
        {"block_number": 3, "builder_paid_usd": 0.0},  # no single-pool swap
    ]


def _three_block_revenue() -> pl.DataFrame:
    """revenue() plus block 3: paid, R = 1e17, Q = 2e16 (share 0.2). Over the paid blocks 1 and
    3 the volume-weighted share is (8e17 + 2e16) / (1e18 + 1e17) = 0.82 / 1.1; the median and
    the mean of the per-block shares (0.8, 0.2) are both 0.5."""
    extra = pl.DataFrame(
        {
            "block_number": [3],
            "miner": [MINER],
            "priority_wei": [10**17],
            "direct_wei": [0],
            "last_from": [MINER],
            "last_value_wei": [2 * 10**16],
        },
        schema=revenue().schema,
    )
    return pl.concat([revenue(), extra])


def test_paid_block_ratio_is_volume_weighted() -> None:
    assert paid_block_ratio(_split(_three_block_revenue())) == pytest.approx(0.82 / 1.1)
    only_self_built = _split(revenue()).filter(pl.col("self_built"))
    assert paid_block_ratio(only_self_built) == 0.0


def test_destination_reports_a_self_built_sensitivity() -> None:
    split = _split(_three_block_revenue())
    aligned = pl.DataFrame(
        {
            "block_number": [1, 2],
            "log_index": [0, 0],
            "tx_hash": ["0xa", "0xb"],
            "flow_label": ["searcher", "searcher"],
            "notional_usd": [1000.0, 1000.0],
            "markout_usd_0": [10.0, 5.0],
            "p_cex_0": [2000.0, 2000.0],
            "protocol_fee_usd": [0.0, 0.0],
        }
    )
    events = pl.DataFrame(
        {
            "tx_hash": ["0xa", "0xb"],
            "block_number": [1, 2],
            "receipt_gas_used": [100_000, 100_000],
            "receipt_effective_gas_price": [3 * 10**9, 2 * 10**9],
        }
    )
    blocks = pl.DataFrame(
        {"block_number": [1, 2], "miner": [MINER] * 2, "base_fee_per_gas": [10**9] * 2}
    )
    direct = pl.DataFrame(schema={"tx_hash": pl.String, "direct_wei": pl.Int128})
    other = pl.DataFrame({"tx_hash": ["0xa", "0xb"], "other_logs": [0, 0], "logs": [1, 1]})
    costs = searcher_costs(aligned, events, blocks, direct, other, split)
    assert costs.sort("tx_hash")["self_built"].to_list() == [False, True]
    steps = pl.DataFrame({"flow_label": ["searcher"], "lvr_0": [20.0], "fee_usd": [1.0]})
    d = destination(steps, aligned, costs, split, sensitivity=True)
    paid_a = 100_000 * 2 * 10**9 / 1e18 * 2000.0  # block 1, paid: proposer share 0.8
    paid_b = 100_000 * 1 * 10**9 / 1e18 * 2000.0  # block 2, self-built: share 1 (primary)
    assert d["proposer_usd"] == pytest.approx(0.8 * paid_a + paid_b)
    assert d["builder_margin_usd"] == pytest.approx(0.2 * paid_a)
    s = d["sensitivity_self_built"]
    ratio = 0.82 / 1.1
    assert s["self_built_proposer_share"] == pytest.approx(ratio)
    assert s["median_paid_block_proposer_share"] == pytest.approx(0.5)  # reported, not used
    assert s["blocks"] == 3 and s["self_built_blocks"] == 1
    assert s["share_blocks_self_built"] == pytest.approx(1 / 3)
    assert s["n_single_pool_swaps_self_built"] == 1
    assert s["builder_paid_usd"] == pytest.approx(paid_a + paid_b)
    assert s["builder_paid_self_built_usd"] == pytest.approx(paid_b)
    assert s["share_builder_paid_self_built"] == pytest.approx(paid_b / (paid_a + paid_b))
    assert s["share_primary_proposer_in_self_built"] == pytest.approx(
        paid_b / (0.8 * paid_a + paid_b)
    )
    assert s["proposer_usd"] == pytest.approx(0.8 * paid_a + ratio * paid_b)
    assert s["builder_margin_usd"] == pytest.approx(0.2 * paid_a + (1 - ratio) * paid_b)
    assert s["proposer_usd"] + s["builder_margin_usd"] == pytest.approx(
        d["proposer_usd"] + d["builder_margin_usd"]
    )  # only the split between the two moves
    assert s["share_proposer"] == pytest.approx(s["proposer_usd"] / 20.0)
    assert s["share_builder_margin"] == pytest.approx(s["builder_margin_usd"] / 20.0)


def test_r3_lists_lp_types_in_a_fixed_order() -> None:
    positions = pl.DataFrame(
        {"lp_type": ["nft_wallet", "jit", "lp_vault", "jit"], "fee_usd": [4.0, 1.0, 2.0, 0.5]}
    )
    rows = check_r3_lp_types(positions).summary["by_lp_type"]
    assert [r["lp_type"] for r in rows] == ["jit", "lp_vault", "nft_wallet"]  # pnl.LP_TYPES order
    assert rows[0] == {"lp_type": "jit", "positions": 2, "fee_usd": 1.5}


PAYER = "0x" + "44" * 20


def _class_world() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Blocks 1-50: PAYER (not the miner) sends the last transaction with value 7 (payout pair);
    block 51: the miner pays 9 (paid); block 52: empty."""
    n = 52
    rev = pl.DataFrame(
        {
            "block_number": list(range(1, n + 1)),
            "miner": [MINER] * n,
            "priority_wei": [100] * (n - 1) + [0],
            "direct_wei": [0] * n,
            "last_from": [PAYER] * 50 + [MINER, None],
            "last_value_wei": [7] * 50 + [9, None],
        },
        schema=revenue().schema,
    )
    last_tx = rev.filter(pl.col("last_from").is_not_null()).select(
        "block_number",
        to_address=pl.lit("0x" + "ee" * 20),
        receipt_gas_used=pl.lit(21000, dtype=pl.Int64),
    )
    return rev, block_classes(rev, last_tx)


def test_split_pays_from_the_payout_address_only_when_asked() -> None:
    rev, classes = _class_world()
    where = pl.col("block_number") == 3
    on = block_split(rev, classes, payouts=True).row(by_predicate=where, named=True)
    off = block_split(rev, classes, payouts=False).row(by_predicate=where, named=True)
    assert on["cls"] == PAYOUT
    assert on["payment_wei"] == on["last_value_wei"] == 7 and not on["self_built"]
    assert off["payment_wei"] == off["revenue_wei"] == 100 and off["self_built"]


def test_empty_blocks_are_not_self_built() -> None:
    rev, classes = _class_world()
    empty = block_split(rev, classes, payouts=False).filter(pl.col("cls") == EMPTY)
    assert empty.height == 1 and not empty["self_built"].any()
    assert empty["payment_wei"].to_list() == [0] and empty["proposer_share"].to_list() == [0.0]


def test_class_table_shares_sum_to_one() -> None:
    _, classes = _class_world()
    single = pl.DataFrame(
        {"block_number": [1, 2, 51], "builder_paid_usd": [3.0, 1.0, 4.0]},
        schema={"block_number": pl.Int64, "builder_paid_usd": pl.Float64},
    )
    t = class_table(classes, single)
    assert t["cls"].to_list() == [EMPTY, PAID, PAYOUT, PROPOSER_IS_FEE_RECIPIENT, UNEXPLAINED]
    assert t["blocks"].to_list() == [1, 1, 50, 0, 0]
    assert t["builder_paid_usd"].to_list() == [0.0, 4.0, 4.0, 0.0, 0.0]
    assert t["share_blocks"].sum() == pytest.approx(1)
    assert t["share_builder_paid_usd"].sum() == pytest.approx(1)


FWD = "0x" + "fe" * 20


def _paths(rows: list[tuple[int, list[str]]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "block_number": [b for b, _ in rows],
            "tx_hash": ["0x" + "11" * 32] * len(rows),
            "path": [",".join(p) for _, p in rows],
        },
        schema=PATH_SCHEMA,
    )


def _forwarded(n: int = 20, off: int = 0) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """`n` found holdout-2 payout blocks paid into the forwarder; the first `off` paths end at
    someone other than the relay's recipient."""
    rows = [
        (i, HOLDOUT2_ROUND, PAYOUT, 10**18, 10**18, PROPOSER, FWD) for i in range(1000, 1000 + n)
    ]
    relays, split = _world(rows)
    return (
        relays,
        split,
        _paths([(i, [FWD, BOT if i < 1000 + off else PROPOSER]) for i in range(1000, 1000 + n)]),
    )


def test_r1d_passes_through_a_forwarder_where_r1b_fails() -> None:
    relays, split, paths = _forwarded(off=1)
    d = holdout_decision(relays, split, HOLDOUT2_ROUND, paths)
    assert d["n_found_payout"] == 20 and d["share_recipient_match"] == pytest.approx(0.95)
    assert d["round"] == HOLDOUT2_ROUND and d["recipient_check"] == "R1d" and d["one_split"]
    assert (
        holdout_decision(*_forwarded(off=2)[:2], HOLDOUT2_ROUND, _forwarded(off=2)[2])["one_split"]
        is False
    )
    assert holdout_decision(relays, split, HOLDOUT2_ROUND, paths.head(0))["one_split"] is False


def test_r1d_fails_without_a_relay_recipient() -> None:
    relays, split, paths = _forwarded()
    relays = relays.with_columns(proposer_fee_recipient=pl.lit(None, dtype=pl.String))
    assert holdout_decision(relays, split, HOLDOUT2_ROUND, paths)["share_recipient_match"] == 0.0


def test_r1d_compares_lowercased() -> None:
    relays, split, paths = _forwarded()
    relays = relays.with_columns(pl.col("proposer_fee_recipient").str.to_uppercase())
    paths = paths.with_columns(pl.col("path").str.to_uppercase())
    assert holdout_decision(relays, split, HOLDOUT2_ROUND, paths)["share_recipient_match"] == 1.0


def test_the_first_holdout_decision_ignores_paths_and_the_second_round() -> None:
    relays, split, paths = _forwarded()
    old = _world(_twenty(off_recipient=1))
    both = pl.concat([old[0], relays]), pl.concat([old[1], split])
    assert holdout_decision(*both) == holdout_decision(*old)
    assert holdout_decision(*both, paths=paths) == holdout_decision(*old)
    r1 = check_r1_relays(both[0], both[1], NO_USD, paths).summary
    assert r1["by_round"][HOLDOUT2_ROUND][PAYOUT]["recipient_match_fwd"] == 20
    assert r1["by_round"][HOLDOUT2_ROUND][PAYOUT]["recipient_match"] == 0  # R1b misses them all
    assert r1["holdout2_by_stratum"]["payout"]["found"] == 20
    assert r1["holdout2_recipient_failures"] == []
    assert r1["sampled"] == 0  # the top-level base leaves out both holdouts


def _holdout2_on_disk(raw: Path, blocks: list[int]) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    drawn = {
        "block_number": blocks,
        "stratum": ["payout"] * len(blocks),
        "seed": [45] * len(blocks),
    }
    write_exact(pl.DataFrame(drawn), raw / HOLDOUT2_FILE)


def test_holdout2_does_not_freeze_without_every_path(tmp_path: Path) -> None:
    relays, split, paths = _forwarded(n=3)
    _holdout2_on_disk(tmp_path, [1000, 1001, 1002])
    assert paths_complete(tmp_path, split, paths) is True
    assert paths_complete(tmp_path, split, paths.head(2)) is False
    fresh = holdout_decision(relays, split, HOLDOUT2_ROUND, paths.head(2))
    kw = {"decision_file": HOLDOUT2_DECISION_FILE, "holdout_file": HOLDOUT2_FILE}
    got = settle_decision(tmp_path, relays, fresh, **kw, round_label=HOLDOUT2_ROUND, ready=False)
    assert got == (fresh, False, None) and not (tmp_path / HOLDOUT2_DECISION_FILE).exists()


def test_holdout2_is_not_ready_before_its_retry_pass(tmp_path: Path) -> None:
    # stopping rule: "fetched, then retried once" — no freeze on data that was never retried
    _, split, paths = _forwarded(n=3)
    _holdout2_on_disk(tmp_path, [1000, 1001, 1002])
    assert holdout2_ready(tmp_path, split, paths) is False
    (tmp_path / HOLDOUT2_RETRIED).write_text("", encoding="utf-8")
    assert holdout2_ready(tmp_path, split, paths) is True
    assert holdout2_ready(tmp_path, split, paths.head(2)) is False


def test_a_complete_holdout2_freezes_in_its_own_file(tmp_path: Path) -> None:
    relays, split, paths = _forwarded(n=3)
    _holdout2_on_disk(tmp_path, [1000, 1001, 1002])
    first = tmp_path / HOLDOUT_DECISION_FILE
    first.write_text('{"decision": {"one_split": false}}', encoding="utf-8")
    before = first.read_bytes()
    fresh = holdout_decision(relays, split, HOLDOUT2_ROUND, paths)
    kw = {"decision_file": HOLDOUT2_DECISION_FILE, "holdout_file": HOLDOUT2_FILE}
    assert settle_decision(tmp_path, relays, fresh, **kw, round_label=HOLDOUT2_ROUND) == (
        fresh,
        True,
        None,
    )
    frozen = json.loads((tmp_path / HOLDOUT2_DECISION_FILE).read_text(encoding="utf-8"))
    assert frozen["decision"] == fresh and frozen["n_holdout_blocks"] == 3
    assert first.read_bytes() == before
