import polars as pl
import pytest

from uniswap_lp_economics.lp.payouts import (
    EMPTY,
    PAID,
    PAYOUT,
    PROPOSER_IS_FEE_RECIPIENT,
    UNEXPLAINED,
    block_classes,
    class_counts,
    payout_pairs,
)


def addr(n: int) -> str:
    return "0x" + f"{n:02x}" * 20


A, B, S_A, P, X = addr(1), addr(2), addr(3), addr(4), addr(5)
# (block, miner, last_from, last_value_wei, to_address); last_from None = no transactions.
Row = tuple[int, str, str | None, int, str | None]


def frames(rows: list[Row]) -> tuple[pl.DataFrame, pl.DataFrame]:
    rev = pl.DataFrame(
        {
            "block_number": [r[0] for r in rows],
            "miner": [r[1] for r in rows],
            "priority_wei": [0] * len(rows),
            "direct_wei": [0] * len(rows),
            "last_from": [r[2] for r in rows],
            "last_value_wei": [r[3] for r in rows],
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
    last = pl.DataFrame(
        {
            "block_number": [r[0] for r in rows if r[2] is not None],
            "to_address": [r[4] for r in rows if r[2] is not None],
            "receipt_gas_used": [21000] * sum(r[2] is not None for r in rows),
        },
        schema={"block_number": pl.Int64, "to_address": pl.String, "receipt_gas_used": pl.Int64},
    )
    return rev, last


def synthetic() -> tuple[pl.DataFrame, pl.DataFrame]:
    rows: list[Row] = [
        (1, A, None, 0, None),  # no transactions
        (2, A, A, 5, X),  # the fee recipient pays the proposer itself
        (3, A, S_A, 10, P),  # A's payout sender pays a proposer
        (4, A, S_A, 0, P),  # payout sender, value 0
        (5, A, S_A, 10, A),  # top-up: payout sender pays A itself
        (6, A, S_A, 10, None),  # contract creation
        (7, B, X, 1, P),  # B never pays
    ]
    rows += [(n, A, S_A, 10, P) for n in range(100, 200)]  # 104 pair blocks, one zero: 99.04%
    return frames(rows)


def test_each_block_gets_one_class() -> None:
    rev, last = synthetic()
    cls = {r["block_number"]: r["cls"] for r in block_classes(rev, last).to_dicts()}
    assert cls[1] == EMPTY
    assert cls[2] == PAID
    assert cls[3] == PAYOUT
    assert cls[4] == UNEXPLAINED
    assert cls[5] == UNEXPLAINED
    assert cls[6] == UNEXPLAINED
    assert cls[7] == PROPOSER_IS_FEE_RECIPIENT
    assert cls[150] == PAYOUT


def test_payout_threshold_is_50_blocks_and_99_percent() -> None:
    def pair_blocks(miner: str, n: int, zeros: int) -> list[Row]:
        sender = addr(int(miner[2:4], 16) + 100)
        return [(i, miner, sender, 0 if i < zeros else 1, P) for i in range(n)]

    c, d, e = addr(10), addr(11), addr(12)
    rows = pair_blocks(c, 49, 0) + pair_blocks(d, 50, 0) + pair_blocks(e, 50, 1)
    rows = [(i, *r[1:]) for i, r in enumerate(rows)]  # unique block numbers
    pairs = payout_pairs(frames(rows)[0])
    assert pairs["miner"].to_list() == [d]


def test_a_non_empty_block_without_a_last_tx_row_raises() -> None:
    rev, last = synthetic()
    with pytest.raises(ValueError, match="block 2"):
        block_classes(rev, last.filter(pl.col("block_number") != 2))


def test_class_counts_report_top_ups() -> None:
    rev, last = synthetic()
    counts = class_counts(block_classes(rev, last))
    assert counts["n_top_up"] == 1
    assert counts[EMPTY] == 1 and counts[PROPOSER_IS_FEE_RECIPIENT] == 1
    assert counts[PAID] == 1 and counts[PAYOUT] == 101 and counts[UNEXPLAINED] == 3
