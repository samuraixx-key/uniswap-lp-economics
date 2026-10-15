from typing import Any

import polars as pl

from uniswap_lp_economics.lp.checks import check_l1
from uniswap_lp_economics.lp.swapfees import build_swap_fees, protocol_cut
from uniswap_lp_economics.tickbook import TickBook
from uniswap_lp_economics.v3math import get_sqrt_ratio_at_tick as sqrt_at
from uniswap_lp_economics.v3swap import swap

L = 10**18
SCHEMA: dict[str, Any] = {
    "block_number": pl.Int64,
    "log_index": pl.Int64,
    "event": pl.String,
    "tick": pl.Int64,
    "sqrt_price_x96": pl.Int128,
    "liquidity": pl.Int128,
    "amount0": pl.Int128,
    "amount1": pl.Int128,
    "fee_protocol0_new": pl.Int64,
    "fee_protocol1_new": pl.Int64,
}


def book() -> TickBook:
    b = TickBook(tick=0, sqrt_price_x96=sqrt_at(0), liquidity=0)
    b.apply_mint(-10, 10, L)
    b.apply_mint(10, 20, 2 * L)
    return b


def events(tamper: bool = False) -> pl.DataFrame:
    r = swap(book(), False, 10**15)  # WETH in: token1 fee, crosses nothing
    return pl.DataFrame(
        [
            {
                "block_number": 1,
                "log_index": 0,
                "event": "set_fee_protocol",
                "fee_protocol0_new": 4,
                "fee_protocol1_new": 4,
            },
            {
                "block_number": 1,
                "log_index": 1,
                "event": "swap",
                "tick": r.tick,
                "sqrt_price_x96": r.sqrt_price_x96,
                "liquidity": r.liquidity,
                "amount0": -r.amount_out + (1 if tamper else 0),
                "amount1": r.amount_in,
            },
        ],
        schema=SCHEMA,
    )


def test_protocol_cut_reads_the_input_tokens_nibble() -> None:
    assert protocol_cut(1001, 4 + (5 << 4), zero_for_one=True) == 250
    assert protocol_cut(1001, 4 + (5 << 4), zero_for_one=False) == 200
    assert protocol_cut(1001, 0, zero_for_one=True) == 0


def test_build_swap_fees_takes_the_protocol_cut_per_step() -> None:
    run = swap(book(), False, 10**15)
    fees = build_swap_fees(events(), book(), 0)
    row = fees.row(0, named=True)
    assert row["mode"] == "exact_input" and row["fee_token"] == "WETH"
    assert row["fee_raw"] == run.fee
    assert row["protocol_fee_raw"] == sum(s.fee // 4 for s in run.steps)
    assert row["lp_fee_raw"] == run.fee - row["protocol_fee_raw"]
    assert row["steps"] == len(run.steps)


def test_l1_fails_on_an_unreproducible_swap() -> None:
    assert check_l1(build_swap_fees(events(), book(), 0)).passed
    bad = check_l1(build_swap_fees(events(tamper=True), book(), 0))
    assert not bad.passed
    assert bad.summary["unreproduced"] == 1
    assert bad.mismatches[0]["block"] == 1


def test_l1_fails_when_the_engine_could_not_match_a_swap() -> None:
    fees = build_swap_fees(events(), book(), 0)
    ok = check_l1(fees, engine_unmatched=0)
    assert ok.passed and ok.summary["engine_unmatched"] == 0
    bad = check_l1(fees, engine_unmatched=2)
    assert not bad.passed and bad.summary["engine_unmatched"] == 2
