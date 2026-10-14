from pathlib import Path

import polars as pl
import pytest

from uniswap_lp_economics import config
from uniswap_lp_economics.flows import (
    label_coverage,
    label_swaps,
    load_labels,
    top_bots,
    top_unlabelled,
)

ROUTER = "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45"
COW = "0x9008d19f58aabd9ed0d60971565aa8510560ab41"
BOT = "0x" + "b0" * 20
CONTRACT = "0x" + "c1" * 20
OTHER = "0x" + "d2" * 20
HEADER = "address,name,category,source_url,notes\n"
GOOD = HEADER + (
    f"{ROUTER},Uniswap SwapRouter02,uniswap_router,https://example.org/a,\n"
    f"{COW},CoW GPv2Settlement,intent_settlement,https://example.org/b,batch auctions\n"
)


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "labels.csv"
    p.write_text(text)
    return p


def swaps(rows: list[tuple[str | None, str, int, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "to_address": pl.String,
            "sender": pl.String,
            "transaction_index": pl.Int64,
            "notional_usd": pl.Float64,
        },
        orient="row",
    )


def test_label_rules_first_match_wins(tmp_path: Path) -> None:
    labels = load_labels(write(tmp_path, GOOD))
    out = label_swaps(
        swaps(
            [
                (ROUTER, ROUTER, 0, 500.0),  # tx target in list
                (COW, BOT, 1, 5_000.0),  # tx target beats a non-listed pool caller
                (OTHER, ROUTER, 2, 50_000.0),  # pool caller in list
                (BOT, BOT, 3, 500_000.0),  # contract called directly: searcher
                (OTHER, CONTRACT, 9, 999.99),
                (None, CONTRACT, 9, 1_000.0),  # contract creation tx
            ]
        ),
        labels,
    )
    assert out["flow_label"].to_list() == [
        "uniswap_router",
        "intent_settlement",
        "uniswap_router",
        "searcher",
        "other_contract",
        "other_contract",
    ]
    assert out["top_of_block"].to_list() == [True, True, True, False, False, False]
    assert out["size_bucket"].to_list() == ["<1k", "1k-10k", "10k-100k", ">=100k", "<1k", "1k-10k"]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (HEADER + f"{ROUTER.upper()},X,uniswap_router,https://e.org,\n", "line 2: address"),
        (HEADER + f"{ROUTER},X,dex,https://e.org,\n", "line 2: category"),
        (HEADER + f"{ROUTER},X,uniswap_router,,\n", "line 2: source_url"),
        (HEADER + f"{ROUTER},,uniswap_router,https://e.org,\n", "line 2: name"),
        (GOOD + f"{ROUTER},Again,uniswap_router,https://e.org,\n", "duplicate"),
        ("address,name,category\n", "columns"),
    ],
)
def test_load_labels_rejects_bad_rows(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        load_labels(write(tmp_path, text))


def test_top_bots_coverage_and_cap() -> None:
    a, b, c = "0x" + "0a" * 20, "0x" + "0b" * 20, "0x" + "0c" * 20
    labelled = swaps([(a, a, 0, 60.0), (b, b, 0, 30.0), (c, c, 0, 10.0), (OTHER, a, 0, 99.0)])
    labelled = labelled.with_columns(
        flow_label=pl.Series(["searcher", "searcher", "searcher", "other_contract"])
    )
    assert top_bots(labelled) == [a, b]
    assert top_bots(labelled, coverage=0.95) == [a, b, c]
    assert top_bots(labelled, cap=1) == [a]
    assert top_bots(labelled.filter(pl.col("flow_label") != "searcher")) == []


def test_coverage_tables(tmp_path: Path) -> None:
    labels = load_labels(write(tmp_path, GOOD))
    labelled = label_swaps(swaps([(ROUTER, ROUTER, 0, 100.0), (OTHER, CONTRACT, 0, 300.0)]), labels)
    cov = label_coverage(labelled)
    assert dict(zip(cov["flow_label"], cov["notional_share"], strict=True)) == {
        "uniswap_router": 0.25,
        "other_contract": 0.75,
    }
    assert top_unlabelled(labelled, "sender")["address"].to_list() == [CONTRACT]


def test_repo_labels_file_is_valid() -> None:
    labels = load_labels(config.LABELS_CSV)
    assert labels.height >= 10
    assert ROUTER in labels["address"].to_list()
