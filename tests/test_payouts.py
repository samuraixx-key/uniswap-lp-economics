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
    draw_holdout,
    payout_pairs,
    recipient_reads,
    recipient_types,
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
        paid: Row = (0, miner, miner, 1, X)  # the fee recipient pays from itself once
        return [paid] + [(i, miner, sender, 0 if i < zeros else 1, P) for i in range(n)]

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


def _classes(rows: list[tuple[int, str, str | None, int]]) -> pl.DataFrame:
    """(block, cls, to_address, receipt_gas_used) rows, each paying 2 ETH."""
    return pl.DataFrame(
        {
            "block_number": [r[0] for r in rows],
            "cls": [r[1] for r in rows],
            "to_address": [r[2] for r in rows],
            "receipt_gas_used": [r[3] for r in rows],
            "last_value_wei": [2 * 10**18] * len(rows),
        },
        schema={
            "block_number": pl.Int64,
            "cls": pl.String,
            "to_address": pl.String,
            "receipt_gas_used": pl.Int64,
            "last_value_wei": pl.Int128,
        },
    )


def test_holdout_is_stratified_seeded_and_excludes_the_old_sample() -> None:
    rows = [(b, PAYOUT, P, 21000) for b in range(1, 21)]
    rows += [(b, PAID, None, 21000) for b in range(21, 31)]
    rows += [(b, PROPOSER_IS_FEE_RECIPIENT, None, 21000) for b in range(31, 41)]
    rows += [(b, UNEXPLAINED, None, 21000) for b in range(41, 51)]
    rows += [(b, EMPTY, None, 0) for b in range(51, 61)]
    classes = _classes(rows)
    exclude = {1, 2, 3, 21, 22, 23}
    h = draw_holdout(classes, exclude=exclude, n=3)
    assert h.group_by("stratum").len().sort("stratum").to_dicts() == [
        {"stratum": "payout", "len": 3},
        {"stratum": "rest", "len": 3},
    ]
    assert h.equals(draw_holdout(classes, exclude=exclude, n=3))  # deterministic
    assert set(h["seed"]) == {44}
    assert not set(h["block_number"]) & exclude
    assert set(h.filter(pl.col("stratum") == "payout")["block_number"]) <= set(range(1, 21))
    assert set(h.filter(pl.col("stratum") == "rest")["block_number"]) <= set(range(21, 51))


def test_a_small_stratum_raises() -> None:
    classes = _classes([(b, PAYOUT, P, 21000) for b in range(1, 6)] + [(9, PAID, None, 21000)])
    with pytest.raises(ValueError, match="rest"):
        draw_holdout(classes, exclude=set(), n=3)


def test_recipient_types_prefer_7702_then_contract() -> None:
    wallet, delegated, contract, simple = addr(10), addr(11), addr(12), addr(13)
    classes = _classes(
        [
            (1, PAYOUT, wallet, 30000),
            (2, PAYOUT, wallet, 30000),
            (3, PAYOUT, delegated, 30000),
            (4, PAYOUT, delegated, 30000),
            (5, PAYOUT, contract, 30000),
            (6, PAYOUT, contract, 30000),
            (7, PAYOUT, simple, 21000),  # no read: a plain transfer is a wallet
            (8, PAID, X, 21000),  # not a payout block
        ]
    )
    assert recipient_reads(classes) == [
        (wallet, 1),
        (wallet, 2),
        (delegated, 3),
        (delegated, 4),
        (contract, 5),
        (contract, 6),
    ]
    deleg = "0xef0100" + "ab" * 20
    code = pl.DataFrame(
        {
            "address": [wallet, wallet, delegated, delegated, contract, contract],
            "block": [1, 2, 3, 4, 5, 6],
            "code": ["0x", "0x", "0x", deleg, "0x6080", "0x6080"],
        },
        schema={"address": pl.String, "block": pl.Int64, "code": pl.String},
    )
    usd = pl.DataFrame(
        {"block_number": [1, 3, 5], "builder_paid_usd": [10.0, 20.0, 40.0]},
        schema={"block_number": pl.Int64, "builder_paid_usd": pl.Float64},
    )
    table, differing = recipient_types(classes, code, usd)
    assert differing == 1
    assert table["type"].to_list() == ["wallet", "7702_wallet", "contract"]
    assert table["payments"].to_list() == [3, 2, 2]  # wallet: two coded as wallets, one plain
    assert table["blocks"].to_list() == [3, 2, 2]
    assert table["paid_eth"].to_list() == [6.0, 4.0, 4.0]
    assert table["builder_paid_usd"].to_list() == [10.0, 20.0, 40.0]


def test_a_missing_code_read_names_the_address() -> None:
    classes = _classes([(1, PAYOUT, P, 30000)])
    empty = pl.DataFrame(schema={"address": pl.String, "block": pl.Int64, "code": pl.String})
    usd = pl.DataFrame(schema={"block_number": pl.Int64, "builder_paid_usd": pl.Float64})
    with pytest.raises(ValueError, match=P):
        recipient_types(classes, empty, usd)


def test_min_blocks_moves_the_pair_threshold() -> None:
    rows: list[Row] = [(n, A, S_A, 10, P) for n in range(30)]  # a pair with 30 blocks
    rev, last = frames([*rows, (30, A, A, 1, X)])  # A also pays from itself once
    assert payout_pairs(rev).height == 0 and payout_pairs(rev, min_blocks=20).height == 1
    assert class_counts(block_classes(rev, last))[PAYOUT] == 0
    assert class_counts(block_classes(rev, last, min_blocks=20))[PAYOUT] == 30
    assert class_counts(block_classes(rev, last, min_blocks=31))[PAYOUT] == 0


def test_a_fee_recipient_that_never_pays_has_no_payout_pair() -> None:
    lido, w = addr(20), addr(21)
    rows: list[Row] = [(n, lido, w, 6, addr(100 + n)) for n in range(60)]  # never from lido
    rev, last = frames(rows)
    assert payout_pairs(rev).height == 0
    assert set(block_classes(rev, last)["cls"].to_list()) == {PROPOSER_IS_FEE_RECIPIENT}
